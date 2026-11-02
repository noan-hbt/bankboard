from __future__ import annotations

from datetime import date, timedelta

from bankboard.analytics.recurring import detect, next_occurrence

T = date(2026, 11, 2)


def monthly(day: int, amounts: list[int], end: date = T) -> list[tuple[date, int]]:
    out = []
    y, m = end.year, end.month
    for i, a in enumerate(reversed(amounts)):
        mm = m - 1 - i
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        out.append((date(yy, mm, day), a))
    return out


def test_monthly_subscription_detected() -> None:
    est = detect(monthly(4, [-1112] * 8), T)
    assert est is not None
    assert est.cadence == "monthly" and est.day_of_month == 4
    assert est.next_expected_date == date(2026, 11, 4)
    assert est.confidence >= 0.95 and est.active


def test_salary_step_change_uses_recent_median() -> None:
    est = detect(monthly(28, [245000] * 7 + [275000] * 5), T)
    assert est is not None and est.expected_cents == 275000


def test_weekly_habit_detected() -> None:
    pts = [(T - timedelta(days=7 * i), -2500 - (i % 3) * 100) for i in range(1, 10)]
    est = detect(pts, T)
    assert est is not None and est.cadence == "weekly"


def test_irregular_spending_rejected() -> None:
    pts = [(T - timedelta(days=d), -1500) for d in (1, 2, 5, 9, 10, 23, 24, 40)]
    assert detect(pts, T) is None


def test_stopped_subscription_marked_inactive() -> None:
    old_end = date(2026, 6, 1)
    est = detect(monthly(4, [-999] * 6, end=old_end), T)
    assert est is None or not est.active


def test_new_subscription_two_identical_occurrences() -> None:
    est = detect([(date(2026, 9, 8), -2200), (date(2026, 10, 8), -2200)], T)
    assert est is not None and est.confidence <= 0.6
    assert detect([(date(2026, 9, 8), -2200), (date(2026, 10, 8), -2650)], T) is None


def test_next_occurrence_clamps_month_end() -> None:
    assert next_occurrence(date(2026, 1, 31), "monthly", 30.44, 31) == date(2026, 2, 28)
