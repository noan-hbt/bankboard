from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from bankboard.api.deps import DB, Ctx, CurrentUser
from bankboard.engines.cashflow import CashflowResult, MonthlyCashflow, compute_cashflow, monthly_cashflow
from bankboard.engines.safe_to_spend import SafeToSpendResult, compute_all
from bankboard.engines.state_score import compute_state_score, diff_scores
from bankboard.engines.timeline import project_liquidity
from bankboard.engines.what_changed import (
    NetWorthChange,
    Preset,
    WhatChanged,
    compare_periods,
    net_worth_change,
)
from bankboard.engines.what_changed import resolve_preset as _resolve
from bankboard.models import FinancialSnapshot
from bankboard.services.data_health import DataHealth, compute_data_health
from bankboard.services.snapshots import previous_snapshot, snapshot_on

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/metrics/cashflow", response_model=CashflowResult)
def cashflow(ctx: Ctx, start: date | None = None, end: date | None = None,
             days: Annotated[int, Query(ge=1, le=730)] = 30) -> CashflowResult:
    end = end or ctx.today
    start = start or end - timedelta(days=days - 1)
    return compute_cashflow(ctx.df, start, end)


@router.get("/metrics/cashflow/monthly", response_model=list[MonthlyCashflow])
def cashflow_monthly(ctx: Ctx, months: Annotated[int, Query(ge=1, le=24)] = 12) -> list[MonthlyCashflow]:
    return monthly_cashflow(ctx.df, ctx.today, months)


@router.get("/safe-to-spend", response_model=list[SafeToSpendResult])
def safe_to_spend(ctx: Ctx) -> list[SafeToSpendResult]:
    return compute_all(ctx.safe_to_spend_inputs())


@router.get("/timeline")
def timeline(ctx: Ctx, days: Annotated[int, Query(ge=1, le=120)] = 30) -> dict[str, Any]:
    from bankboard.engines.cashflow import average_daily_spend

    events = [e for e in ctx.expected if e.expected_date < ctx.today + timedelta(days=days)]
    projection = project_liquidity(ctx.today, ctx.spending_cash(), ctx.expected_items(),
                                   average_daily_spend(ctx.df, ctx.today, 90), days)
    return {
        "events": [{"expected_date": e.expected_date, "label": e.label, "kind": e.kind,
                    "category_key": e.category_key, "expected_amount": e.expected_amount,
                    "range_min": e.range_min, "range_max": e.range_max, "confidence": float(e.confidence),
                    "prediction_source": e.prediction_source} for e in events],
        "projection": projection.model_dump(),
    }


@router.get("/what-changed", response_model=WhatChanged)
def what_changed(ctx: Ctx, preset: Preset = "30d", start: date | None = None,
                 end: date | None = None) -> WhatChanged:
    dates = ctx.salary_dates()
    try:
        cur, prev = _resolve(preset, ctx.today, last_salary=dates[-1] if dates else None,
                             previous_salary=dates[-2] if len(dates) > 1 else None, start=start, end=end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return compare_periods(ctx.df, cur, prev, ctx.category_labels)


@router.get("/net-worth-change", response_model=NetWorthChange)
def nw_change(ctx: Ctx, db: DB, days: Annotated[int, Query(ge=1, le=365)] = 7) -> NetWorthChange:
    start = ctx.today - timedelta(days=days)
    s = snapshot_on(db, ctx.user.id, start)
    start_value = s.net_worth if s else sum(ctx.balances_on(start).values(), Decimal(0))
    return net_worth_change(ctx.df, start, ctx.today, start_value, ctx.net_worth(), ctx.category_labels)


@router.get("/state")
def state(ctx: Ctx, db: DB) -> dict[str, Any]:
    score = compute_state_score(ctx.state_inputs(ctx.today))
    prev = previous_snapshot(db, ctx.user.id, ctx.today - timedelta(days=6))
    changes = diff_scores(prev.details.get("subscores", []), score.subscores) if prev else []
    return {"score": score.model_dump(), "previous_score": float(prev.financial_score)
            if prev and prev.financial_score is not None else None,
            "previous_date": prev.snapshot_date if prev else None,
            "changes": [c.model_dump() for c in changes]}


@router.get("/snapshots")
def snapshots(user: CurrentUser, db: DB, days: Annotated[int, Query(ge=1, le=3650)] = 365) -> list[dict[str, Any]]:
    from bankboard.core.clock import today

    rows = db.scalars(select(FinancialSnapshot).where(
        FinancialSnapshot.user_id == user.id, FinancialSnapshot.snapshot_date >= today() - timedelta(days=days))
        .order_by(FinancialSnapshot.snapshot_date))
    return [{"date": s.snapshot_date, "net_worth": s.net_worth, "liquid_assets": s.liquid_assets, "cash": s.cash,
             "monthly_income": s.monthly_income, "monthly_expenses": s.monthly_expenses,
             "savings_rate": s.savings_rate, "financial_score": s.financial_score,
             "safe_to_spend": s.safe_to_spend, "reconstructed": s.is_reconstructed} for s in rows]


@router.get("/snapshots/{day}")
def snapshot_at(day: date, user: CurrentUser, db: DB) -> dict[str, Any]:
    s = snapshot_on(db, user.id, day)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No snapshot at or before this date")
    return {"date": s.snapshot_date, "requested": day, "net_worth": s.net_worth, "liquid_assets": s.liquid_assets,
            "cash": s.cash, "monthly_income": s.monthly_income, "monthly_expenses": s.monthly_expenses,
            "savings_rate": s.savings_rate, "financial_score": s.financial_score, "details": s.details,
            "reconstructed": s.is_reconstructed}


@router.get("/data-health", response_model=DataHealth)
def data_health(ctx: Ctx, db: DB) -> DataHealth:
    return compute_data_health(db, ctx)
