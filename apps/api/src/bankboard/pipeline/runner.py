"""Pipeline orchestration. Every step is replayable from transaction_raw-derived projections."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankboard.core.clock import today as clock_today
from bankboard.models import Account, Transaction, User
from bankboard.pipeline.classify import apply_classification, build_classifier
from bankboard.pipeline.merchants import resolve_merchants
from bankboard.pipeline.recurring import refresh_recurring
from bankboard.pipeline.transfers import apply_transfers

PIPELINE_VERSION = 1


@dataclass(frozen=True)
class PipelineResult:
    transactions: int
    transfers: int
    recurring_patterns: int


def run_pipeline(session: Session, user_id: uuid.UUID, *, today: date | None = None) -> PipelineResult:
    """Full replay for one user: merchants -> transfers -> classification -> recurring."""
    today = today or clock_today()
    user = session.get(User, user_id)
    own_names = {user.display_name.upper()} if user and user.display_name else set()
    txs = list(session.scalars(
        select(Transaction).where(Transaction.user_id == user_id).order_by(Transaction.booking_date)))
    accounts = list(session.scalars(select(Account).where(Account.user_id == user_id)))

    resolve_merchants(session, user_id, txs)
    conf = apply_transfers(txs, accounts, own_names)
    classifier = build_classifier(session, user_id, txs)
    apply_classification(classifier, txs, conf)
    for t in txs:
        t.pipeline_version = PIPELINE_VERSION
    session.flush()
    patterns = refresh_recurring(session, user_id, txs, today)
    return PipelineResult(transactions=len(txs), transfers=len(conf), recurring_patterns=patterns)


__all__ = ["PIPELINE_VERSION", "PipelineResult", "run_pipeline"]
