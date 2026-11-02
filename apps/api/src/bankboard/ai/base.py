"""Provider-agnostic LLM contract.

The LLM never computes financial figures: it can only call typed tools backed by deterministic
engines, and every number in its answer is checked against those tool outputs.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    output: dict[str, Any]


@dataclass
class ChatTurn:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class LLMAnswer:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider: str = ""
    refused: bool = False
    unverified_numbers: list[str] = field(default_factory=list)


class LLMProvider(Protocol):
    name: str

    def answer(self, *, system: str, history: list[ChatTurn], question: str,
               tools: list[ToolSpec]) -> LLMAnswer: ...


_NUM = re.compile(r"\d[\d\s .,]*\d|\d")


def _norm(token: str) -> str:
    t = token.replace(" ", "").replace(" ", "")
    if "," in t and "." not in t:
        t = t.replace(",", ".")
    t = t.replace(",", "")
    try:
        return f"{abs(float(t)):.2f}"
    except ValueError:
        return t


def _collect(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _collect(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect(v, out)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.add(f"{abs(float(obj)):.2f}")
        if isinstance(obj, float) and abs(obj) <= 1:
            out.add(f"{abs(obj) * 100:.2f}")  # ratios rendered as percentages
            out.add(f"{round(abs(obj) * 100):.2f}")
    elif isinstance(obj, str):
        for m in _NUM.findall(obj):
            out.add(_norm(m))
            with contextlib.suppress(ValueError):
                out.add(f"{round(abs(float(_norm(m)))):.2f}")


def unverified_numbers(text: str, calls: list[ToolCall], question: str = "") -> list[str]:
    """Numbers in the answer that appear in no tool output nor in the question (guardrail)."""
    known: set[str] = set()
    for c in calls:
        _collect(c.output, known)
        _collect(c.input, known)
    _collect(question, known)
    bad = []
    for m in _NUM.findall(text):
        n = _norm(m)
        try:
            value = float(n)
        except ValueError:
            continue
        if value < 10 and float(n).is_integer():
            continue  # small counts / ordinals
        if n not in known and f"{round(value):.2f}" not in known:
            bad.append(m.strip())
    return bad
