"""Persist recurring patterns and regenerate expected transactions (replayable)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from bankboard.analytics.recurring import RecurringEstimate, detect, occurrences_until, previous_business_day
from bankboard.core.money import from_cents, to_cents
from bankboard.models import ExpectedTransaction, Merchant, RecurringPattern, Transaction

FORECAST_DAYS = 120
SUBSCRIPTION_CATEGORIES = {"subscriptions", "utilities", "insurance"}


def _series_key(tx: Transaction) -> str:
    direction = "in" if tx.amount > 0 else "out"
    who = str(tx.merchant_id) if tx.merchant_id else tx.label_normalized
    return f"{who}|{direction}|{tx.category_key}|{tx.account_id}"


NON_SUBSCRIPTION_CATEGORIES = {"cash", "internal_transfer", "investment", "housing", "debt", "taxes"}


def _is_subscription(est: RecurringEstimate, category: str, kind: str, direction: str) -> bool:
    if direction != "out" or kind != "consumption" or category in NON_SUBSCRIPTION_CATEGORIES:
        return False
    if category in SUBSCRIPTION_CATEGORIES:
        return True
    return est.cadence in {"monthly", "yearly"} and est.amount_stability > 0.95


def refresh_recurring(session: Session, user_id: uuid.UUID, txs: Sequence[Transaction], today: date) -> int:
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in txs:
        if t.is_excluded:
            continue  # pending included: they are real and prevent re-predicting an occurrence
        groups[_series_key(t)].append(t)

    existing = {p.series_key: p for p in session.scalars(
        select(RecurringPattern).where(RecurringPattern.user_id == user_id))}
    merchants = {m.id: m for m in session.scalars(select(Merchant).where(
        Merchant.id.in_({t.merchant_id for t in txs if t.merchant_id})))}

    for t in txs:
        t.recurring_pattern_id = None
    seen: set[str] = set()
    for key, items in groups.items():
        est = detect([(t.booking_date, to_cents(t.amount)) for t in items], today)
        if est is None:
            continue
        seen.add(key)
        sample = max(items, key=lambda t: t.booking_date)
        direction = "in" if sample.amount > 0 else "out"
        merchant = merchants.get(sample.merchant_id) if sample.merchant_id else None
        pattern = existing.get(key)
        if pattern is None:
            pattern = RecurringPattern(id=uuid.uuid4(), user_id=user_id, series_key=key)
            session.add(pattern)
            existing[key] = pattern
        if pattern.status == "ignored":
            continue
        pattern.merchant_id = sample.merchant_id
        pattern.account_id = sample.account_id
        pattern.label = merchant.name if merchant else sample.label
        pattern.direction = direction
        pattern.kind = sample.kind
        pattern.category_key = sample.category_key
        pattern.cadence = est.cadence
        pattern.period_days = Decimal(str(est.period_days))
        pattern.day_of_month = est.day_of_month
        pattern.mean_amount = from_cents(est.expected_cents)
        pattern.amount_std = from_cents(est.std_cents)
        pattern.amount_min = from_cents(est.min_cents)
        pattern.amount_max = from_cents(est.max_cents)
        pattern.occurrences = est.occurrences
        pattern.first_date = est.first_date
        pattern.last_date = est.last_date
        pattern.next_expected_date = (previous_business_day(est.next_expected_date) if direction == "in"
                                      else est.next_expected_date)
        pattern.confidence = Decimal(str(est.confidence))
        pattern.is_subscription = _is_subscription(est, sample.category_key, sample.kind, direction)
        pattern.is_salary = direction == "in" and sample.category_key == "salary"
        pattern.status = "active" if est.active else "stopped"
        for t in items:
            t.recurring_pattern_id = pattern.id
    for key, pattern in existing.items():
        if key not in seen and pattern.status == "active":
            pattern.status = "stopped"
    session.flush()
    regenerate_expected(session, user_id, today)
    return len(seen)


def regenerate_expected(session: Session, user_id: uuid.UUID, today: date) -> None:
    session.execute(delete(ExpectedTransaction).where(ExpectedTransaction.user_id == user_id,
                                                      ExpectedTransaction.status == "pending"))
    horizon = today + timedelta(days=FORECAST_DAYS)
    patterns = session.scalars(select(RecurringPattern).where(
        RecurringPattern.user_id == user_id, RecurringPattern.status == "active"))
    for p in patterns:
        if p.next_expected_date is None:
            continue
        period = float(p.period_days)
        dates = occurrences_until(p.next_expected_date, horizon, p.cadence, period, p.day_of_month)
        spread = max(p.amount_std * 2, abs(p.mean_amount) * Decimal("0.01"))
        lo = min(p.mean_amount - spread, p.amount_min)
        hi = max(p.mean_amount + spread, p.amount_max)
        for i, d in enumerate(dates):
            conf = float(p.confidence) * (0.985 ** i)
            if p.direction == "in":
                d = previous_business_day(d)
            if d < today:
                d = today  # overdue but still plausible: expected imminently
            stable = p.amount_std <= abs(p.mean_amount) * Decimal("0.1")
            source = ("income" if p.direction == "in" else "subscription" if p.is_subscription
                      else "recurring" if stable else "behavior")
            session.add(ExpectedTransaction(
                id=uuid.uuid4(), user_id=user_id, pattern_id=p.id, account_id=p.account_id, label=p.label,
                category_key=p.category_key, kind=p.kind, expected_date=d,
                expected_amount=p.mean_amount.quantize(Decimal("0.01")),
                range_min=lo.quantize(Decimal("0.01")), range_max=hi.quantize(Decimal("0.01")),
                confidence=Decimal(str(round(conf, 3))), prediction_source=source, status="pending",
            ))
    session.flush()
