"""Injectable clock so engines and tests never depend on wall time implicitly."""

from __future__ import annotations

from datetime import UTC, date, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return utcnow().date()
