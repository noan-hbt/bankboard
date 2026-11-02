"""Recurring series detection. Pure: takes dated amounts, returns a pattern estimate or None."""

from __future__ import annotations

import calendar
import itertools
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

# cadence -> (nominal period days, min interval, max interval, tolerance days)
CADENCES: dict[str, tuple[float, int, int, int]] = {
    "weekly": (7.0, 6, 8, 2),
    "biweekly": (14.0, 12, 16, 3),
    "monthly": (30.44, 26, 35, 5),
    "bimonthly": (60.88, 54, 68, 8),
    "quarterly": (91.31, 82, 100, 10),
    "yearly": (365.25, 350, 380, 15),
}
MIN_OCCURRENCES = {"weekly": 4, "biweekly": 3, "monthly": 2, "bimonthly": 3, "quarterly": 3, "yearly": 2}
TWO_POINT_MAX_CONFIDENCE = 0.6  # a brand-new monthly charge seen twice with the exact same amount
MIN_CONFIDENCE = 0.55


@dataclass(frozen=True)
class RecurringEstimate:
    cadence: str
    period_days: float
    day_of_month: int | None
    mean_cents: int
    expected_cents: int  # median of the last 3 occurrences: robust to step changes (raise)
    std_cents: int
    min_cents: int
    max_cents: int
    occurrences: int
    first_date: date
    last_date: date
    next_expected_date: date
    confidence: float
    regularity: float
    amount_stability: float
    active: bool


def _add_months(d: date, months: int, day_of_month: int) -> date:
    month_index = d.month - 1 + months
    y, m = d.year + month_index // 12, month_index % 12 + 1
    return date(y, m, min(day_of_month, calendar.monthrange(y, m)[1]))


def previous_business_day(d: date) -> date:
    """Salaries due on a weekend are paid on the Friday before."""
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def next_occurrence(last: date, cadence: str, period_days: float, day_of_month: int | None) -> date:
    if cadence in {"monthly", "bimonthly", "quarterly", "yearly"} and day_of_month:
        months = {"monthly": 1, "bimonthly": 2, "quarterly": 3, "yearly": 12}[cadence]
        return _add_months(last, months, day_of_month)
    return last + timedelta(days=round(period_days))


def occurrences_until(start: date, end: date, cadence: str, period_days: float,
                      day_of_month: int | None, limit: int = 60) -> list[date]:
    out: list[date] = []
    current = start
    while current <= end and len(out) < limit:
        out.append(current)
        current = next_occurrence(current, cadence, period_days, day_of_month)
    return out


def detect(points: list[tuple[date, int]], today: date) -> RecurringEstimate | None:
    """points: (date, signed amount in cents), any order. Same-day duplicates are collapsed."""
    if len(points) < 2:
        return None
    by_day: dict[date, int] = {}
    for d, c in points:
        by_day[d] = by_day.get(d, 0) + c
    days = sorted(by_day)
    amounts = [by_day[d] for d in days]
    if len(days) < 2:
        return None
    intervals = [(b - a).days for a, b in itertools.pairwise(days)]
    median_interval = statistics.median(intervals)

    cadence = next((k for k, (_, lo, hi, _) in CADENCES.items() if lo <= median_interval <= hi), None)
    if cadence is None or len(days) < MIN_OCCURRENCES[cadence]:
        return None
    nominal, _, _, tol = CADENCES[cadence]
    regular = sum(1 for i in intervals if abs(i - nominal) <= tol) / len(intervals)

    mean = statistics.fmean(amounts)
    std = statistics.pstdev(amounts) if len(amounts) > 1 else 0.0
    cv = abs(std / mean) if mean else 1.0
    amount_stability = max(0.0, 1.0 - cv / 0.5)
    count_score = min(1.0, len(days) / 6)

    dom: int | None = None
    if cadence in {"monthly", "bimonthly", "quarterly", "yearly"}:
        dom = round(statistics.median(d.day for d in days))
    next_date = next_occurrence(days[-1], cadence, nominal, dom)
    overdue_days = (today - next_date).days
    active = overdue_days <= tol * 2
    recency = 1.0 if overdue_days <= tol else max(0.0, 1 - (overdue_days - tol) / (nominal + tol))

    confidence = (0.5 * regular + 0.3 * amount_stability + 0.2 * count_score) * recency
    if len(days) == 2:
        if amount_stability < 0.95 or regular < 1.0:
            return None
        confidence = min(confidence, TWO_POINT_MAX_CONFIDENCE)
    if confidence < MIN_CONFIDENCE and active:
        return None
    if not active and confidence * (1 / max(recency, 1e-9)) < MIN_CONFIDENCE:
        return None
    return RecurringEstimate(
        cadence=cadence, period_days=nominal, day_of_month=dom, mean_cents=round(mean),
        expected_cents=round(statistics.median(amounts[-3:])),
        std_cents=round(std), min_cents=min(amounts), max_cents=max(amounts), occurrences=len(days),
        first_date=days[0], last_date=days[-1], next_expected_date=next_date,
        confidence=round(min(1.0, confidence), 3), regularity=round(regular, 3),
        amount_stability=round(amount_stability, 3), active=active,
    )
