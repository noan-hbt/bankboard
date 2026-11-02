"""Cashflow, safe-to-spend, timeline, What Changed and score: pure engine tests (no database)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import polars as pl

from bankboard.analytics.frames import TX_SCHEMA
from bankboard.engines.cashflow import compute_cashflow
from bankboard.engines.common import DateSpan
from bankboard.engines.safe_to_spend import (
    ExpectedItem,
    GoalCommitment,
    SafeToSpendInputs,
    compute_safe_to_spend,
)
from bankboard.engines.state_score import StateInputs, compute_state_score, diff_scores, piecewise
from bankboard.engines.timeline import project_liquidity
from bankboard.engines.what_changed import compare_periods, net_worth_change, resolve_preset

T = date(2026, 11, 2)  # Monday


def frame(rows: list[tuple[date, int, str, str]], recurring: set[int] | None = None) -> pl.DataFrame:
    recurring = recurring or set()
    data = [{
        "id": str(i), "account_id": "a", "booking_date": d, "amount": cents, "kind": kind, "category_key": cat,
        "category_confidence": 0.9, "merchant_id": cat, "merchant": cat.title(), "label": cat, "status": "booked",
        "is_essential": cat in {"groceries", "housing"}, "is_spending_account": True,
        "recurring": i in recurring, "hour": 12,
    } for i, (d, cents, kind, cat) in enumerate(rows)]
    return pl.DataFrame(data, schema=TX_SCHEMA)


def test_cashflow_exact_cents_and_exclusions() -> None:
    df = frame([
        (T, 245000, "income", "salary"),
        (T, -1, "consumption", "groceries"),
        (T, -3333, "consumption", "groceries"),
        (T, 1000, "refund", "groceries"),
        (T, -25000, "transfer", "internal_transfer"),
        (T, 25000, "transfer", "internal_transfer"),
        (T, -20000, "investment", "investment"),
        (T, -250, "fee", "fees"),
    ])
    r = compute_cashflow(df, T, T)
    assert r.income == Decimal("2450.00")
    assert r.expenses == Decimal("25.84")  # 0.01 + 33.33 − 10.00 + 2.50
    assert r.net == Decimal("2424.16")
    assert r.invested == Decimal("200.00")  # investment is not an expense
    assert r.savings_rate == round(242416 / 245000, 4)
    assert {c.category_key for c in r.by_category} == {"groceries", "fees"}


def test_safe_to_spend_formula_and_horizons() -> None:
    inp = SafeToSpendInputs(
        today=T, spending_cash=Decimal("2840"), cash_lines=[("Courant", Decimal("2840"))],
        expected=[
            ExpectedItem(T + timedelta(days=1), Decimal("-650"), "Loyer", "consumption", Decimal("0.98")),
            ExpectedItem(T + timedelta(days=3), Decimal("-71"), "Assurance", "consumption", Decimal("0.9")),
            ExpectedItem(T + timedelta(days=5), Decimal("-30"), "Peu probable", "consumption", Decimal("0.3")),
            ExpectedItem(T + timedelta(days=20), Decimal("-250"), "Épargne", "transfer", Decimal("0.95")),
            ExpectedItem(T + timedelta(days=26), Decimal("1550"), "Salaire", "income", Decimal("0.96")),
        ],
        buffer=Decimal("900"), buffer_detail="test", daily_essential_variable=Decimal("10"),
        goals=[GoalCommitment("Voyage", Decimal("30.44"))],
        next_income_date=T + timedelta(days=26),
    )
    week = compute_safe_to_spend(inp, "week")
    assert week.end_date == date(2026, 11, 8) and week.days == 7
    assert week.obligations == Decimal("721.00")  # low-confidence event ignored
    assert week.goals == Decimal("7.00")
    assert week.value == Decimal("2840") - 721 - 900 - 7 - 70
    lines = {ln.label: ln.amount for ln in week.explanation.lines}
    assert lines["Safe to spend"] == week.value
    until = compute_safe_to_spend(inp, "until_next_income")
    assert until.end_date == T + timedelta(days=25)
    assert until.planned_savings == Decimal("250.00")
    assert until.value < week.value  # income is never added
    today = compute_safe_to_spend(inp, "today")
    assert today.days == 1 and today.obligations == 0


def test_liquidity_projection_lowest_point() -> None:
    items = [ExpectedItem(T + timedelta(days=1), Decimal("-850"), "Loyer", "consumption", Decimal("1")),
             ExpectedItem(T + timedelta(days=5), Decimal("2000"), "Salaire", "income", Decimal("0.9"))]
    p = project_liquidity(T, Decimal("1000"), items, Decimal("10"), days=10)
    assert p.lowest.date == T + timedelta(days=4)
    assert p.lowest.balance == Decimal("1000") - 850 - 50
    assert p.end_balance == Decimal("1000") - 850 + 2000 - 100


def test_what_changed_drivers_and_calendar_effects() -> None:
    cur, prev = resolve_preset("7d", T)
    assert cur.days == prev.days == 7
    rows = [
        (prev.start, -10000, "consumption", "restaurants"), (cur.start, -19100, "consumption", "restaurants"),
        (prev.start, -2000, "consumption", "transport"), (cur.start, -6300, "consumption", "transport"),
        (prev.start, -5000, "consumption", "groceries"), (cur.start, -4000, "consumption", "groceries"),
        (cur.start, -85000, "consumption", "housing"),  # rent falls in the current window only
    ]
    wc = compare_periods(frame(rows, recurring={6}), cur, prev, {"restaurants": "Restaurants"})
    assert wc.variable_delta == Decimal("124.00")  # 91 + 43 − 10
    assert wc.category_drivers[0].key == "restaurants" and wc.category_drivers[0].delta == Decimal("91.00")
    assert abs(wc.category_drivers[0].share_of_change - 91 / 134) < 1e-3
    assert wc.recurring_drivers[0].key == "housing"
    assert wc.expenses_delta == Decimal("974.00")
    assert "Restaurants".lower() in wc.headline


def test_net_worth_change_reports_residual() -> None:
    rows = [(T, 38800, "income", "salary"), (T, -11900, "consumption", "restaurants"),
            (T, -6200, "consumption", "subscriptions"), (T, -2300, "fee", "fees")]
    r = net_worth_change(frame(rows), T - timedelta(days=1), T, Decimal("1000"), Decimal("1184"))
    flows = {f.label: f.amount for f in r.flows}
    assert flows["Revenus"] == Decimal("388.00") and flows["Abonnements"] == Decimal("-62.00")
    assert r.change == Decimal("184.00") and r.unexplained == Decimal("0.00")
    r2 = net_worth_change(frame(rows), T - timedelta(days=1), T, Decimal("1000"), Decimal("1200"))
    assert r2.unexplained == Decimal("16.00")


def test_state_score_explainable_and_diff() -> None:
    assert piecewise(-5, [(0, 0), (1, 10)]) == 0 and piecewise(0.5, [(0, 0), (1, 10)]) == 5
    good = compute_state_score(StateInputs(Decimal("9000"), Decimal("1500"), Decimal("2000"), 0.2, 0.05, 0.95,
                                           None, 1.0))
    bad = compute_state_score(StateInputs(Decimal("500"), Decimal("1500"), Decimal("2000"), -0.05, 0.5, 1.4,
                                          None, 1.0))
    assert 0 <= bad.score < good.score <= 100
    assert abs(sum(s.points for s in good.subscores) - good.score) < 0.1
    assert abs(sum(s.weight for s in good.subscores) - 1) < 1e-3  # goal weight renormalized away
    changes = diff_scores(bad.subscores, good.subscores)
    assert changes and all(c.delta_points > 0 for c in changes)


def test_custom_preset_requires_bounds() -> None:
    _cur, prev = resolve_preset("custom", T, start=date(2026, 10, 1), end=date(2026, 10, 31))
    assert prev == DateSpan(start=date(2026, 8, 31), end=date(2026, 9, 30), label="période précédente")
