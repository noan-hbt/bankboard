"""Shared result types: every engine output is explainable."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ExplainLine(BaseModel):
    label: str
    amount: Decimal | None = None
    op: Literal["+", "-", "=", "·"] = "·"
    detail: str | None = None
    ref: str | None = None


class Explanation(BaseModel):
    method: str
    lines: list[ExplainLine] = Field(default_factory=list)
    confidence: float = 1.0


class DateSpan(BaseModel):
    start: date
    end: date
    label: str | None = None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1
