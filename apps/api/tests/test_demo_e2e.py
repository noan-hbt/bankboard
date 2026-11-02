"""Full vertical slice through the real code path: connect -> sync -> pipeline -> snapshots -> insights."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bankboard.demo.seed import connect_demo
from bankboard.models import (
    BankConnection,
    FinancialSnapshot,
    Insight,
    RecurringPattern,
    Transaction,
    TransactionRaw,
    User,
)
from bankboard.providers.demo.provider import DemoProvider
from bankboard.services.analysis import refresh_user
from bankboard.services.sync import sync_connection
from conftest import TODAY


def test_demo_end_to_end(db: Session, user: User) -> None:
    connect_demo(db, user, today=TODAY)
    db.commit()
    n_raw = db.scalar(select(func.count()).select_from(TransactionRaw))
    n_tx = db.scalar(select(func.count()).select_from(Transaction))
    assert n_raw and n_raw > 500 and n_tx == n_raw

    # every transaction is enriched
    assert db.scalar(select(func.count()).select_from(Transaction).where(Transaction.pipeline_version == 0)) == 0
    salary = list(db.scalars(select(RecurringPattern).where(RecurringPattern.is_salary)))
    assert len(salary) == 1 and str(salary[0].mean_amount) == "2750.0000"
    # internal transfers detected in pairs
    transfers = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.kind == "transfer"))
    assert transfers and transfers % 2 == 0
    assert db.scalar(select(func.count()).select_from(FinancialSnapshot)) >= 365
    titles = [i.title for i in db.scalars(select(Insight))]
    assert any("Double débit" in t for t in titles)

    # re-sync + re-analysis: no duplicate transactions, no duplicate insights
    conn = db.scalars(select(BankConnection)).one()
    sync_connection(db, conn.id, provider=DemoProvider(today=TODAY), today=TODAY)
    refresh_user(db, user.id, today=TODAY)
    db.commit()
    assert db.scalar(select(func.count()).select_from(Transaction)) == n_tx
    assert len([i.title for i in db.scalars(select(Insight))]) == len(titles)


def test_next_day_sync_turns_pending_into_booked(db: Session, user: User) -> None:
    connect_demo(db, user, today=TODAY)
    db.commit()
    pending_before = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.status == "pending"))
    conn = db.scalars(select(BankConnection)).one()
    tomorrow = date.fromordinal(TODAY.toordinal() + 1)
    sync_connection(db, conn.id, provider=DemoProvider(today=tomorrow), today=tomorrow)
    # yesterday's pending rows are now booked: no pending row older than tomorrow-1 remains
    stale = db.scalar(select(func.count()).select_from(Transaction).where(
        Transaction.status == "pending", Transaction.booking_date < date.fromordinal(tomorrow.toordinal() - 1)))
    assert pending_before is not None and stale == 0


def test_undecryptable_session_marks_reauth(db: Session, user: User) -> None:
    import pytest

    from bankboard.models import BankSession
    from bankboard.providers.base import ProviderError

    connect_demo(db, user, today=TODAY)
    db.commit()
    bs = db.scalars(select(BankSession)).one()
    bs.session_ref_enc = "not-a-valid-token"
    db.commit()
    conn = db.scalars(select(BankConnection)).one()
    with pytest.raises(ProviderError):
        sync_connection(db, conn.id, provider=DemoProvider(today=TODAY), today=TODAY)
    db.refresh(conn)
    assert conn.status == "reauth_required"
