"""Load ledger data into Polars frames (amounts in integer cents for exact arithmetic)."""

from __future__ import annotations

import uuid
from datetime import date

import polars as pl
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from bankboard.core.money import to_cents
from bankboard.models import Account, Category, Merchant, Transaction

TX_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "id": pl.Utf8,
    "account_id": pl.Utf8,
    "booking_date": pl.Date,
    "amount": pl.Int64,  # cents, signed
    "kind": pl.Utf8,
    "category_key": pl.Utf8,
    "category_confidence": pl.Float64,
    "merchant_id": pl.Utf8,
    "merchant": pl.Utf8,
    "label": pl.Utf8,
    "status": pl.Utf8,
    "is_essential": pl.Boolean,
    "is_spending_account": pl.Boolean,
    "recurring": pl.Boolean,
    "hour": pl.Int32,
}

SPENDING_KINDS = ("consumption", "fee", "debt_payment")


def empty_tx_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=TX_SCHEMA)


def load_transactions(session: Session, user_id: uuid.UUID, start: date | None = None,
                      end: date | None = None, *, currency: str = "EUR") -> pl.DataFrame:
    essential = {
        c.key: c.is_essential for c in session.scalars(
            select(Category).where(or_(Category.user_id.is_(None), Category.user_id == user_id)))
    }
    q = (
        select(Transaction, Merchant.name, Account.is_spending)
        .join(Account, Account.id == Transaction.account_id)
        .outerjoin(Merchant, Merchant.id == Transaction.merchant_id)
        .where(Transaction.user_id == user_id, Transaction.is_excluded.is_(False),
               Transaction.currency == currency)
    )
    conds = []
    if start:
        conds.append(Transaction.booking_date >= start)
    if end:
        conds.append(Transaction.booking_date <= end)
    if conds:
        q = q.where(and_(*conds))
    rows = []
    for tx, merchant_name, is_spending in session.execute(q):
        rows.append({
            "id": str(tx.id),
            "account_id": str(tx.account_id),
            "booking_date": tx.booking_date,
            "amount": to_cents(tx.amount),
            "kind": tx.kind,
            "category_key": tx.category_key,
            "category_confidence": float(tx.category_confidence),
            "merchant_id": str(tx.merchant_id) if tx.merchant_id else None,
            "merchant": merchant_name or tx.label,
            "label": tx.label,
            "status": tx.status,
            "is_essential": essential.get(tx.category_key, False),
            "is_spending_account": bool(is_spending),
            "recurring": tx.recurring_pattern_id is not None,
            "hour": tx.booked_at.hour if tx.booked_at else None,
        })
    if not rows:
        return empty_tx_frame()
    return pl.DataFrame(rows, schema=TX_SCHEMA)


def between(df: pl.DataFrame, start: date, end: date) -> pl.DataFrame:
    return df.filter((pl.col("booking_date") >= start) & (pl.col("booking_date") <= end))


def spend_expr() -> pl.Expr:
    """Positive cents of spending for a row (refunds count negative: they reduce spending)."""
    return (
        pl.when(pl.col("kind").is_in(SPENDING_KINDS)).then(-pl.col("amount"))
        .when(pl.col("kind") == "refund").then(-pl.col("amount"))
        .otherwise(0)
    )
