"""OpenRouter implementation of LLMProvider (OpenAI-compatible chat completions + tool calls).

The API key lives only in the backend environment (OPENROUTER_API_KEY). Tool outputs are the
only source of numbers; the model receives no raw database access.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from bankboard.ai.base import ChatTurn, LLMAnswer, ToolCall, ToolSpec

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8


class LLMError(RuntimeError):
    pass


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, *, api_key: str, model: str, base_url: str = "https://openrouter.ai/api/v1",
                 app_url: str | None = None, transport: httpx.BaseTransport | None = None,
                 timeout: float = 120.0) -> None:
        if not api_key:
            raise ValueError("OpenRouter API key missing")
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}", "X-Title": "Bankboard"}
        if app_url:
            headers["HTTP-Referer"] = app_url
        self._client = httpx.Client(base_url=base_url, headers=headers, timeout=timeout, transport=transport)

    def __repr__(self) -> str:  # never expose the key
        return f"OpenRouterProvider(model={self.model!r})"

    def _complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self._client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"OpenRouter unreachable ({type(exc).__name__})") from exc
        if r.status_code >= 400:
            log.warning("openrouter error status=%s", r.status_code)
            raise LLMError(f"OpenRouter error {r.status_code}")
        data: dict[str, Any] = r.json()
        if data.get("error"):
            raise LLMError(f"OpenRouter error: {str(data['error'].get('message', ''))[:120]}")
        return data

    def answer(self, *, system: str, history: list[ChatTurn], question: str, tools: list[ToolSpec]) -> LLMAnswer:
        registry = {t.name: t for t in tools}
        tool_defs = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                       "parameters": t.input_schema}} for t in tools]
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages += [{"role": h.role, "content": h.content} for h in history]
        messages.append({"role": "user", "content": question})
        calls: list[ToolCall] = []

        for _ in range(MAX_TOOL_ROUNDS):
            data = self._complete({"model": self.model, "messages": messages, "tools": tool_defs,
                                   "tool_choice": "auto", "max_tokens": 4000})
            choice = data["choices"][0]
            msg = choice.get("message") or {}
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                return LLMAnswer(text=str(msg.get("content") or "").strip(), tool_calls=calls,
                                 provider=f"{self.name}:{data.get('model', self.model)}",
                                 refused=choice.get("finish_reason") == "content_filter")
            messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = str(fn.get("name"))
                try:
                    spec = registry[name]
                    args = json.loads(fn.get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be an object")
                    output = spec.handler(args)
                    calls.append(ToolCall(name=name, input=args, output=output))
                    content = json.dumps(output, ensure_ascii=False)
                except Exception as exc:  # report to the model, never crash the turn
                    log.warning("tool %s failed: %s", name, type(exc).__name__)
                    content = json.dumps({"error": f"tool error: {type(exc).__name__}"})
                messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": content})
        return LLMAnswer(text="Analyse interrompue (trop d'appels d'outils).", tool_calls=calls, provider=self.name)
