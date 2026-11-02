"""Detector contract: a pure function of the FinancialContext returning structured insights."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from bankboard.services.context import FinancialContext

Section = Literal["attention", "opportunity", "info"]
Priority = Literal["info", "useful", "important", "critical"]


@dataclass(frozen=True)
class InsightDraft:
    type: str
    fingerprint: str
    title: str
    importance: float  # 0..1
    confidence: float  # 0..1
    section: Section = "attention"
    priority: Priority = "useful"
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    suggested_actions: list[dict[str, Any]] = field(default_factory=list)


Detector = Callable[["FinancialContext"], list[InsightDraft]]


def priority_for(importance: float, confidence: float) -> Priority:
    s = importance * confidence
    if s >= 0.75:
        return "critical"
    if s >= 0.5:
        return "important"
    if s >= 0.25:
        return "useful"
    return "info"
