from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select

from bankboard.api.deps import DB, CurrentUser, Today
from bankboard.api.schemas import AccountOut, AccountPatch, TransactionOut, TransactionPage, TransactionPatch
from bankboard.models import Account, Category, Merchant, RecurringPattern, Transaction
from bankboard.services.analysis import refresh_user
from bankboard.services.context import _latest_balances

router = APIRouter(prefix="/api", tags=["ledger"])


@router.get("/accounts", response_model=list[AccountOut])
def accounts(user: CurrentUser, db: DB) -> list[AccountOut]:
    accs = list(db.scalars(select(Account).where(Account.user_id == user.id).order_by(Account.created_at)))
    bal = _latest_balances(db, accs)
    return [AccountOut(id=a.id, name=a.name, iban_masked=a.iban_masked, currency=a.currency,
                       account_type=a.account_type, is_liquid=a.is_liquid, is_spending=a.is_spending,
                       balance=bal[a.id].amount if a.id in bal else None,
                       balance_date=bal[a.id].reference_date if a.id in bal else None,
                       last_synced_at=a.last_synced_at) for a in accs]


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def patch_account(account_id: uuid.UUID, body: AccountPatch, user: CurrentUser, db: DB, today: Today) -> AccountOut:
    a = db.get(Account, account_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(a, k, v)
    db.flush()
    refresh_user(db, user.id, today=today, backfill_days=365)
    return next(x for x in accounts(user, db) if x.id == account_id)


@router.get("/categories")
def categories(user: CurrentUser, db: DB) -> list[dict[str, object]]:
    rows = db.scalars(select(Category).where(or_(Category.user_id.is_(None), Category.user_id == user.id))
                      .order_by(Category.name))
    return [{"key": c.key, "name": c.name, "parent_key": c.parent_key, "is_essential": c.is_essential,
             "default_kind": c.default_kind, "color": c.color} for c in rows]


def _tx_out(t: Transaction, merchant: str | None) -> TransactionOut:
    return TransactionOut(
        id=t.id, account_id=t.account_id, booking_date=t.booking_date, status=t.status, amount=t.amount,
        currency=t.currency, label=t.label, merchant=merchant, merchant_id=t.merchant_id, kind=t.kind,
        kind_confidence=t.kind_confidence, kind_source=t.kind_source, category_key=t.category_key,
        category_confidence=t.category_confidence, category_source=t.category_source,
        is_recurring=t.recurring_pattern_id is not None, is_transfer=t.transfer_group_id is not None,
        is_excluded=t.is_excluded, note=t.note)


@router.get("/transactions", response_model=TransactionPage)
def transactions(
    user: CurrentUser, db: DB,
    start: date | None = None, end: date | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    category: str | None = None, kind: str | None = None, account_id: uuid.UUID | None = None,
    merchant_id: uuid.UUID | None = None, min_amount: Decimal | None = None, max_amount: Decimal | None = None,
    recurring: bool | None = None, max_confidence: float | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100, offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionPage:
    conds = [Transaction.user_id == user.id]
    if start:
        conds.append(Transaction.booking_date >= start)
    if end:
        conds.append(Transaction.booking_date <= end)
    if q:
        like = f"%{q}%"
        conds.append(or_(Transaction.label.ilike(like), Transaction.label_normalized.ilike(like),
                         Merchant.name.ilike(like)))
    if category:
        conds.append(Transaction.category_key == category)
    if kind:
        conds.append(Transaction.kind == kind)
    if account_id:
        conds.append(Transaction.account_id == account_id)
    if merchant_id:
        conds.append(Transaction.merchant_id == merchant_id)
    if min_amount is not None:
        conds.append(Transaction.amount >= min_amount)
    if max_amount is not None:
        conds.append(Transaction.amount <= max_amount)
    if recurring is not None:
        conds.append(Transaction.recurring_pattern_id.is_not(None) if recurring
                     else Transaction.recurring_pattern_id.is_(None))
    if max_confidence is not None:
        conds.append(Transaction.category_confidence <= max_confidence)
    if status_:
        conds.append(Transaction.status == status_)
    base = select(Transaction, Merchant.name).outerjoin(Merchant, Merchant.id == Transaction.merchant_id).where(*conds)
    total, total_sum = db.execute(
        select(func.count(), func.coalesce(func.sum(Transaction.amount), 0))
        .select_from(Transaction).outerjoin(Merchant, Merchant.id == Transaction.merchant_id).where(*conds)).one()
    rows = db.execute(base.order_by(Transaction.booking_date.desc(), Transaction.created_at.desc())
                      .limit(limit).offset(offset))
    items = [_tx_out(t, m) for t, m in rows]
    return TransactionPage(items=items, total=total, sum_amount=Decimal(total_sum))


@router.patch("/transactions/{tx_id}", response_model=TransactionOut)
def patch_transaction(tx_id: uuid.UUID, body: TransactionPatch, user: CurrentUser, db: DB,
                      today: Today) -> TransactionOut:
    t = db.get(Transaction, tx_id)
    if t is None or t.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    targets = [t]
    if body.apply_to_merchant and t.merchant_id:
        targets = list(db.scalars(select(Transaction).where(Transaction.user_id == user.id,
                                                            Transaction.merchant_id == t.merchant_id)))
    for x in targets:
        if body.category_key is not None:
            x.category_key, x.category_source, x.category_confidence = body.category_key, "manual", Decimal(1)
        if body.kind is not None:
            x.kind, x.kind_source, x.kind_confidence = body.kind, "manual", Decimal(1)
            if body.kind == "transfer":
                x.transfer_source = "manual"
                x.transfer_group_id = x.transfer_group_id or uuid.uuid4()
            elif x.transfer_group_id is not None:
                x.transfer_source, x.transfer_group_id = "manual", None
    if body.note is not None:
        t.note = body.note
    if body.is_excluded is not None:
        t.is_excluded = body.is_excluded
    db.flush()
    refresh_user(db, user.id, today=today, backfill_days=90)
    merchant = db.get(Merchant, t.merchant_id) if t.merchant_id else None
    return _tx_out(t, merchant.name if merchant else None)


@router.get("/recurring")
def recurring(user: CurrentUser, db: DB) -> list[dict[str, object]]:
    rows = db.scalars(select(RecurringPattern).where(RecurringPattern.user_id == user.id,
                                                     RecurringPattern.status == "active")
                      .order_by(RecurringPattern.mean_amount))
    return [{"id": str(p.id), "label": p.label, "direction": p.direction, "kind": p.kind,
             "category_key": p.category_key, "cadence": p.cadence, "amount": p.mean_amount,
             "amount_min": p.amount_min, "amount_max": p.amount_max, "occurrences": p.occurrences,
             "next_expected_date": p.next_expected_date, "confidence": p.confidence,
             "is_subscription": p.is_subscription, "is_salary": p.is_salary,
             "annual_amount": (p.mean_amount * Decimal("365.25") / p.period_days).quantize(Decimal("0.01"))}
            for p in rows]
