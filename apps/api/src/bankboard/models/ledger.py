from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from bankboard.models.base import Base, created_at, pk, updated_at

Confidence = Numeric(4, 3)


class TransactionRaw(Base):
    __tablename__ = "transaction_raw"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    provider: Mapped[str]
    provider_transaction_id: Mapped[str | None]
    dedup_key: Mapped[str]
    status: Mapped[str]
    payload: Mapped[dict[str, Any]]
    payload_hash: Mapped[str]
    payload_history: Mapped[list[Any]] = mapped_column(default=list)
    first_seen_at: Mapped[datetime] = created_at()
    last_seen_at: Mapped[datetime] = created_at()


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    raw_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transaction_raw.id", ondelete="CASCADE"))
    status: Mapped[str]
    booking_date: Mapped[date]
    value_date: Mapped[date | None]
    booked_at: Mapped[datetime | None]
    amount: Mapped[Decimal]
    currency: Mapped[str] = mapped_column(String(3))
    original_amount: Mapped[Decimal | None]
    original_currency: Mapped[str | None] = mapped_column(String(3))
    label: Mapped[str]
    label_normalized: Mapped[str]
    counterparty_name: Mapped[str | None]
    counterparty_iban_hash: Mapped[str | None]
    mcc: Mapped[str | None]
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("merchants.id", ondelete="SET NULL"))
    merchant_source: Mapped[str | None]
    kind: Mapped[str] = mapped_column(default="consumption")
    kind_confidence: Mapped[Decimal] = mapped_column(Confidence, default=Decimal(0))
    kind_source: Mapped[str] = mapped_column(default="rule")
    category_key: Mapped[str] = mapped_column(default="uncategorized")
    category_confidence: Mapped[Decimal] = mapped_column(Confidence, default=Decimal(0))
    category_source: Mapped[str] = mapped_column(default="rule")
    transfer_group_id: Mapped[uuid.UUID | None]
    transfer_source: Mapped[str | None]
    recurring_pattern_id: Mapped[uuid.UUID | None]
    is_excluded: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str | None]
    pipeline_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    dimension: Mapped[str]
    value: Mapped[str]


class TransactionTag(Base):
    __tablename__ = "transaction_tags"
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(default="manual")
    confidence: Mapped[Decimal] = mapped_column(Confidence, default=Decimal(1))
