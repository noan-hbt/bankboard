"""Daily financial snapshots (persisted Financial State history) with historical backfill."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from bankboard.core.clock import utcnow
from bankboard.core.money import from_cents, q
from bankboard.engines.safe_to_spend import compute_safe_to_spend
from bankboard.engines.state_score import compute_state_score
from bankboard.models import FinancialSnapshot
from bankboard.services.context import FinancialContext

BACKFILL_DAYS = 365


def snapshot_values(ctx: FinancialContext, d: date) -> dict[str, Any]:
    balances = ctx.balances_on(d)
    accounts = ctx.base_accounts
    net_worth = q(sum((balances.get(a.id, Decimal(0)) for a in accounts), Decimal(0)))
    liquid = q(sum((balances.get(a.id, Decimal(0)) for a in accounts if a.is_liquid), Decimal(0)))
    cash = q(sum((balances.get(a.id, Decimal(0)) for a in accounts if a.is_spending), Decimal(0)))
    investments = q(sum((balances.get(a.id, Decimal(0)) for a in accounts if a.account_type == "investment"),
                        Decimal(0)))
    liabilities = q(-sum((min(balances.get(a.id, Decimal(0)), Decimal(0)) for a in accounts
                          if a.account_type in {"credit", "loan"}), Decimal(0)))
    income = ctx.series.trailing("income", d, 30)
    expenses = ctx.series.trailing("spend", d, 30)
    savings_rate = round((income - expenses) / income, 4) if income > 0 else None
    # A score needs at least 90 days of history to mean anything.
    score = compute_state_score(ctx.state_inputs(d)) if ctx.history_days(d) >= 90 else None
    safe = None
    if d == ctx.today:
        safe = compute_safe_to_spend(ctx.safe_to_spend_inputs(), "until_next_income").value
    goals = [g for g in ctx.goals if g.status == "active"]
    goal_progress = (Decimal(str(round(sum(min(1.0, float(g.current_amount / g.target_amount)) for g in goals)
                                       / len(goals), 4))) if goals else None)
    return {
        "snapshot_date": d, "net_worth": net_worth, "liquid_assets": liquid, "cash": cash,
        "investments": investments, "liabilities": liabilities, "monthly_income": from_cents(income),
        "monthly_expenses": from_cents(expenses),
        "savings_rate": Decimal(str(savings_rate)) if savings_rate is not None else None,
        "safe_to_spend": safe, "financial_score": Decimal(str(score.score)) if score else None,
        "goal_progress": goal_progress,
        "data_confidence": Decimal(str(ctx.data_confidence)),
        "details": {
            "subscores": [s.model_dump(mode="json") for s in score.subscores] if score else [],
            "accounts": {str(k): str(v) for k, v in balances.items()},
            "grade": score.grade if score else None,
        },
        "is_reconstructed": d != ctx.today,
    }


def upsert_snapshot(session: Session, user_id: uuid.UUID, values: dict[str, Any]) -> None:
    stmt = pg_insert(FinancialSnapshot).values(id=uuid.uuid4(), user_id=user_id, computed_at=utcnow(), **values)
    update = {k: stmt.excluded[k] for k in values if k != "snapshot_date"}
    update["computed_at"] = stmt.excluded.computed_at
    session.execute(stmt.on_conflict_do_update(index_elements=["user_id", "snapshot_date"], set_=update))


def refresh_snapshots(session: Session, ctx: FinancialContext, *, backfill_days: int = BACKFILL_DAYS) -> int:
    """Today's snapshot always; reconstructed history for days that have none (or were reconstructed)."""
    existing = {
        s.snapshot_date: s.is_reconstructed
        for s in session.scalars(select(FinancialSnapshot).where(
            FinancialSnapshot.user_id == ctx.user.id,
            FinancialSnapshot.snapshot_date >= ctx.today - timedelta(days=backfill_days)))
    }
    earliest_tx = ctx.first_transaction_date or ctx.today
    start = max(ctx.today - timedelta(days=backfill_days), earliest_tx)
    count = 0
    d = start
    while d <= ctx.today:
        # real (non reconstructed) past snapshots are never overwritten
        if d == ctx.today or d not in existing or existing[d]:
            upsert_snapshot(session, ctx.user.id, snapshot_values(ctx, d))
            count += 1
        d += timedelta(days=1)
    return count


def previous_snapshot(session: Session, user_id: uuid.UUID, before: date) -> FinancialSnapshot | None:
    return session.scalars(select(FinancialSnapshot).where(
        FinancialSnapshot.user_id == user_id, FinancialSnapshot.snapshot_date < before)
        .order_by(FinancialSnapshot.snapshot_date.desc())).first()


def snapshot_on(session: Session, user_id: uuid.UUID, d: date) -> FinancialSnapshot | None:
    return session.scalars(select(FinancialSnapshot).where(
        FinancialSnapshot.user_id == user_id, FinancialSnapshot.snapshot_date <= d)
        .order_by(FinancialSnapshot.snapshot_date.desc())).first()
