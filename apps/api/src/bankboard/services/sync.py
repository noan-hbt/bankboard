"""Idempotent bank synchronization.

raw (append-only) -> projection (transactions) -> pending reconciliation -> balances -> events.
Running the same sync N times yields the same state.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from cryptography.fernet import InvalidToken
from sqlalchemy import delete, func, select, text, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from bankboard.core.clock import today as clock_today
from bankboard.core.clock import utcnow
from bankboard.core.crypto import CryptoError, decrypt, iban_hash
from bankboard.events.bus import publish
from bankboard.models import (
    Account,
    Balance,
    BankConnection,
    BankSession,
    SyncJob,
    Transaction,
    TransactionRaw,
)
from bankboard.pipeline.text import normalize_label
from bankboard.providers.base import (
    BankingProvider,
    DateRange,
    ProviderError,
    ProviderTransaction,
    SessionRef,
)
from bankboard.providers.registry import get_provider
from bankboard.services.dedup import dedup_keys, payload_hash

log = logging.getLogger(__name__)

INITIAL_HISTORY_DAYS = 730
OVERLAP_DAYS = 10
MAX_PAYLOAD_HISTORY = 10


@dataclass
class SyncStats:
    accounts: int = 0
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    pending_removed: int = 0
    balances: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {k: v for k, v in self.__dict__.items()}


def _projection_fields(tx: ProviderTransaction) -> dict[str, object]:
    label_source = " ".join([tx.counterparty_name or "", *tx.remittance]) or tx.label
    return {
        "status": tx.status,
        "booking_date": tx.booking_date,
        "value_date": tx.value_date,
        "booked_at": tx.booked_at,
        "amount": tx.amount,
        "currency": tx.currency,
        "original_amount": tx.original_amount,
        "original_currency": tx.original_currency,
        "label": tx.label[:300],
        "label_normalized": normalize_label(label_source)[:300],
        "counterparty_name": tx.counterparty_name,
        "counterparty_iban_hash": iban_hash(tx.counterparty_iban),
        "mcc": tx.mcc,
    }


def ingest_transactions(
    session: Session, *, user_id: uuid.UUID, account: Account, provider_key: str,
    transactions: list[ProviderTransaction], window: DateRange, stats: SyncStats,
) -> None:
    keys = dedup_keys(transactions)
    existing = {
        r.dedup_key: r
        for r in session.scalars(
            select(TransactionRaw).where(TransactionRaw.account_id == account.id,
                                         TransactionRaw.dedup_key.in_(keys))
        )
    } if keys else {}
    projections = {
        t.raw_id: t
        for t in session.scalars(
            select(Transaction).where(Transaction.raw_id.in_([r.id for r in existing.values()]))
        )
    } if existing else {}
    now = utcnow()
    observed_pending: set[str] = set()
    to_create: list[Transaction] = []

    for tx, key in zip(transactions, keys, strict=True):
        stats.fetched += 1
        if tx.status == "pending":
            observed_pending.add(key)
        h = payload_hash(tx.raw)
        raw = existing.get(key)
        if raw is None:
            raw = TransactionRaw(
                id=uuid.uuid4(), user_id=user_id, account_id=account.id, provider=provider_key,
                provider_transaction_id=tx.provider_transaction_id, dedup_key=key, status=tx.status,
                payload=tx.raw, payload_hash=h, payload_history=[], first_seen_at=now, last_seen_at=now,
            )
            session.add(raw)
            existing[key] = raw
            stats.inserted += 1
            changed = True
        else:
            raw.last_seen_at = now
            changed = raw.payload_hash != h
            if changed:
                # Keep the first observation intact; record the revision.
                history = list(raw.payload_history)[-(MAX_PAYLOAD_HISTORY - 1):]
                history.append({"observed_at": now.isoformat(), "payload": tx.raw})
                raw.payload_history = history
                raw.payload_hash = h
                raw.status = tx.status
                stats.updated += 1
            else:
                stats.unchanged += 1

        proj = projections.get(raw.id)
        fields = _projection_fields(tx)
        if proj is None:
            to_create.append(Transaction(id=uuid.uuid4(), user_id=user_id, account_id=account.id,
                                         raw_id=raw.id, pipeline_version=0, **fields))
        elif changed:
            for k, v in fields.items():
                setattr(proj, k, v)
            proj.pipeline_version = 0  # needs enrichment again
    session.flush()  # raw rows first (no ORM relationship to order inserts)
    session.add_all(to_create)
    session.flush()

    # Pending transactions are ephemeral: drop projections not re-observed in this window.
    stale = select(Transaction.id).join(TransactionRaw, TransactionRaw.id == Transaction.raw_id).where(
        Transaction.account_id == account.id,
        Transaction.status == "pending",
        Transaction.booking_date >= window.start,
        Transaction.booking_date <= window.end,
        TransactionRaw.dedup_key.not_in(observed_pending) if observed_pending else true(),
    )
    stale_ids = list(session.scalars(stale))
    if stale_ids:
        session.execute(delete(Transaction).where(Transaction.id.in_(stale_ids)))
        stats.pending_removed += len(stale_ids)


def _sync_window(account: Account, today: date) -> DateRange:
    if account.last_synced_booking_date:
        start = account.last_synced_booking_date - timedelta(days=OVERLAP_DAYS)
    else:
        start = today - timedelta(days=INITIAL_HISTORY_DAYS)
    return DateRange(start=min(start, today), end=today)


def sync_connection(
    session: Session, connection_id: uuid.UUID, *, provider: BankingProvider | None = None,
    today: date | None = None,
) -> SyncJob:
    """Synchronize one connection. Commits its own work; safe to call repeatedly."""
    today = today or clock_today()
    connection = session.get(BankConnection, connection_id)
    if connection is None:
        raise ValueError("Unknown connection")
    job = SyncJob(id=uuid.uuid4(), user_id=connection.user_id, connection_id=connection.id,
                  status="running", started_at=utcnow(), stats={})
    session.add(job)
    session.commit()

    stats = SyncStats()
    try:
        # Serialize syncs of the same connection.
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": str(connection.id)})
        bank_session = session.scalars(
            select(BankSession).where(BankSession.connection_id == connection.id,
                                      BankSession.revoked_at.is_(None))
            .order_by(BankSession.created_at.desc())
        ).first()
        if bank_session is None:
            raise ProviderError("consent_expired", "No active bank session")
        try:
            ref = SessionRef(decrypt(bank_session.session_ref_enc))
        except (InvalidToken, CryptoError) as exc:  # encryption key changed or missing
            raise ProviderError("auth", "Stored bank session cannot be decrypted; reconnect the bank") from exc
        provider = provider or get_provider(connection.provider)

        accounts = list(session.scalars(
            select(Account).where(Account.connection_id == connection.id, Account.is_active.is_(True))
        ))
        for account in accounts:
            if account.provider_account_ref is None:
                continue
            stats.accounts += 1
            window = _sync_window(account, today)
            txs = provider.get_transactions(ref, account.provider_account_ref, window)
            ingest_transactions(session, user_id=connection.user_id, account=account,
                                provider_key=connection.provider, transactions=txs, window=window,
                                stats=stats)
            for bal in provider.get_balances(ref, account.provider_account_ref):
                session.execute(
                    pg_insert(Balance).values(
                        id=uuid.uuid4(), account_id=account.id, balance_type=bal.balance_type,
                        amount=bal.amount, currency=bal.currency, reference_date=bal.reference_date,
                    ).on_conflict_do_update(
                        index_elements=["account_id", "balance_type", "reference_date"],
                        set_={"amount": bal.amount, "fetched_at": func.now()},
                    )
                )
                stats.balances += 1
            booked_dates = [t.booking_date for t in txs if t.status == "booked"]
            if booked_dates:
                latest = max(booked_dates)
                if account.last_synced_booking_date is None or latest > account.last_synced_booking_date:
                    account.last_synced_booking_date = latest
            account.last_synced_at = utcnow()

        connection.status = "active"
        connection.last_synced_at = utcnow()
        connection.last_error = None
        job.status = "succeeded"
        job.finished_at = utcnow()
        job.stats = stats.as_dict()
        publish(session, connection.user_id, "bank.sync.completed",
                {"connection_id": str(connection.id), "job_id": str(job.id), "stats": stats.as_dict(),
                 "as_of": today.isoformat()})
        session.commit()
    except ProviderError as exc:
        session.rollback()
        _record_failure(session, connection.id, job.id, exc.kind, str(exc))
        raise
    except Exception as exc:
        session.rollback()
        _record_failure(session, connection.id, job.id, "internal", type(exc).__name__)
        raise
    return job


def _record_failure(session: Session, connection_id: uuid.UUID, job_id: uuid.UUID, kind: str,
                    message: str) -> None:
    connection = session.get(BankConnection, connection_id)
    job = session.get(SyncJob, job_id)
    if connection is not None:
        connection.status = "reauth_required" if kind in {"consent_expired", "auth"} else "error"
        connection.last_error = f"{kind}: {message}"[:500]
        connection.last_error_at = utcnow()
    if job is not None:
        job.status = "failed"
        job.finished_at = utcnow()
        job.error = f"{kind}: {message}"[:500]
    session.commit()
    log.warning("sync failed connection=%s kind=%s", connection_id, kind)
