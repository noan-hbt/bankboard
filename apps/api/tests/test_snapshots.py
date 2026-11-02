from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bankboard.models import Balance, FinancialSnapshot, User
from bankboard.services.context import build_context
from bankboard.services.snapshots import refresh_snapshots
from factories import add_tx, make_account

T = date(2026, 11, 2)


def test_balance_reconstruction_and_snapshot_upsert(db: Session, user: User) -> None:
    acc = make_account(db, user)
    db.add(Balance(id=uuid.uuid4(), account_id=acc.id, balance_type="CLBD", amount=Decimal("1000"),
                   currency="EUR", reference_date=T))
    add_tx(db, acc, T - timedelta(days=2), "-100", "SHOP", kind="consumption", category_key="shopping")
    add_tx(db, acc, T - timedelta(days=1), "500", "SALAIRE", kind="income", category_key="salary")
    add_tx(db, acc, T, "-30", "PENDING", status="pending")  # CLBD excludes pending
    db.flush()
    ctx = build_context(db, user.id, T)
    assert ctx.balances_on(T)[acc.id] == Decimal("1000")
    assert ctx.balances_on(T - timedelta(days=1))[acc.id] == Decimal("1000")
    assert ctx.balances_on(T - timedelta(days=2))[acc.id] == Decimal("500")
    assert ctx.balances_on(T - timedelta(days=3))[acc.id] == Decimal("600")

    n1 = refresh_snapshots(db, ctx, backfill_days=5)
    n2 = refresh_snapshots(db, ctx, backfill_days=5)
    assert n1 == n2 == 3  # from first transaction date to today
    assert db.scalar(select(func.count()).select_from(FinancialSnapshot)) == 3
    snap = db.scalars(select(FinancialSnapshot).where(FinancialSnapshot.snapshot_date == T)).one()
    assert snap.net_worth == Decimal("1000") and not snap.is_reconstructed
    assert snap.monthly_income == Decimal("500") and snap.monthly_expenses == Decimal("130")
    assert snap.financial_score is None  # < 90 days of history: no misleading score
    past = db.scalars(select(FinancialSnapshot).where(FinancialSnapshot.snapshot_date == T - timedelta(days=2))).one()
    assert past.is_reconstructed and past.net_worth == Decimal("500")
