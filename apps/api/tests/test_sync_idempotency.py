from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bankboard.models import Transaction, TransactionRaw, User
from bankboard.providers.base import DateRange
from bankboard.services.dedup import dedup_keys
from bankboard.services.sync import SyncStats, ingest_transactions
from factories import make_account, ptx

D = date(2026, 10, 15)
WINDOW = DateRange(D - timedelta(days=10), D)


def _count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def test_dedup_keys_prefer_provider_id_and_rank_identical_rows() -> None:
    a = ptx(D, "-3.50", "CAFE", id=None)
    b = ptx(D, "-3.50", "CAFE", id=None)
    c = ptx(D, "-12.00", "SHOP", id="abc")
    keys = dedup_keys([a, b, c])
    assert keys[2] == "id:abc"
    assert keys[0] != keys[1]  # two genuine identical coffees stay two transactions
    assert keys[0].endswith("#0") and keys[1].endswith("#1")
    assert dedup_keys([a, b, c]) == keys  # deterministic


def test_resync_is_idempotent(db: Session, user: User) -> None:
    acc = make_account(db, user)
    batch = [ptx(D, "-3.50", "CAFE"), ptx(D, "-3.50", "CAFE"), ptx(D - timedelta(days=1), "-40", "SHOP", id="x1")]
    for _ in range(3):
        stats = SyncStats()
        ingest_transactions(db, user_id=user.id, account=acc, provider_key="test", transactions=batch,
                            window=WINDOW, stats=stats)
    assert _count(db, TransactionRaw) == 3
    assert _count(db, Transaction) == 3
    assert stats.inserted == 0 and stats.unchanged == 3


def test_changed_payload_keeps_original_and_records_revision(db: Session, user: User) -> None:
    acc = make_account(db, user)
    first = ptx(D, "-40", "SHOP", id="x1")
    ingest_transactions(db, user_id=user.id, account=acc, provider_key="t", transactions=[first], window=WINDOW,
                        stats=SyncStats())
    revised = ptx(D, "-41", "SHOP", id="x1")
    stats = SyncStats()
    ingest_transactions(db, user_id=user.id, account=acc, provider_key="t", transactions=[revised],
                        window=WINDOW, stats=stats)
    raw = db.scalars(select(TransactionRaw)).one()
    assert raw.payload["amount"] == "-40"  # first observation is never destroyed
    assert raw.payload_history[-1]["payload"]["amount"] == "-41"
    tx = db.scalars(select(Transaction)).one()
    assert str(tx.amount) == "-41.0000" and stats.updated == 1


def test_pending_replaced_by_booked(db: Session, user: User) -> None:
    acc = make_account(db, user)
    pending = ptx(D, "-25", "RESTO", status="pending")
    ingest_transactions(db, user_id=user.id, account=acc, provider_key="t", transactions=[pending], window=WINDOW,
                        stats=SyncStats())
    assert _count(db, Transaction) == 1
    booked = ptx(D, "-25", "RESTO", id="b1")
    stats = SyncStats()
    ingest_transactions(db, user_id=user.id, account=acc, provider_key="t", transactions=[booked], window=WINDOW,
                        stats=stats)
    txs = list(db.scalars(select(Transaction)))
    assert len(txs) == 1 and txs[0].status == "booked"
    assert stats.pending_removed == 1


def test_pending_outside_window_is_kept(db: Session, user: User) -> None:
    acc = make_account(db, user)
    old = ptx(D - timedelta(days=30), "-9", "OLD", status="pending")
    ingest_transactions(db, user_id=user.id, account=acc, provider_key="t", transactions=[old],
                        window=DateRange(D - timedelta(days=40), D), stats=SyncStats())
    ingest_transactions(db, user_id=user.id, account=acc, provider_key="t", transactions=[], window=WINDOW,
                        stats=SyncStats())
    assert _count(db, Transaction) == 1
