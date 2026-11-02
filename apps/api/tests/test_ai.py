from __future__ import annotations

import json

import httpx

from bankboard.ai.base import ChatTurn, ToolCall, ToolSpec, unverified_numbers
from bankboard.ai.openrouter_provider import OpenRouterProvider


def test_guardrail_flags_invented_numbers() -> None:
    calls = [ToolCall("get_safe_to_spend", {}, {"value": 617.0, "rate": 0.314})]
    assert unverified_numbers("Tu peux dépenser 617 € (31,4 %).", calls) == []
    assert unverified_numbers("Tu peux dépenser 1 250 €.", calls) == ["1 250"]


def test_openrouter_tool_loop() -> None:
    requests: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        requests.append(body)
        assert req.headers["authorization"] == "Bearer sk-test"
        if len(requests) == 1:
            assert body["tools"][0]["function"]["name"] == "get_safe_to_spend"
            return httpx.Response(200, json={"model": "m", "choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "get_safe_to_spend", "arguments": "{}"}}]}}]})
        tool_msg = body["messages"][-1]
        assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"]) == {"value": 617}
        return httpx.Response(200, json={"model": "m", "choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "Tu peux dépenser 617 €."}}]})

    p = OpenRouterProvider(api_key="sk-test", model="anthropic/claude-opus-5.5",
                           transport=httpx.MockTransport(handler))
    tool = ToolSpec("get_safe_to_spend", "d", {"type": "object", "properties": {}}, lambda _: {"value": 617})
    ans = p.answer(system="s", history=[ChatTurn("user", "hi"), ChatTurn("assistant", "hello")],
                   question="Combien ?", tools=[tool])
    assert ans.text == "Tu peux dépenser 617 €." and [c.name for c in ans.tool_calls] == ["get_safe_to_spend"]
    assert "sk-test" not in repr(p)
