from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from bankboard.models.base import Base, created_at, pk, updated_at


class RecurringPattern(Base):
    __tablename__ = "recurring_patterns"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    series_key: Mapped[str]
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("merchants.id", ondelete="SET NULL"))
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    label: Mapped[str]
    direction: Mapped[str]
    kind: Mapped[str]
    category_key: Mapped[str]
    cadence: Mapped[str]
    period_days: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    day_of_month: Mapped[int | None]
    mean_amount: Mapped[Decimal]
    amount_std: Mapped[Decimal]
    amount_min: Mapped[Decimal]
    amount_max: Mapped[Decimal]
    occurrences: Mapped[int]
    first_date: Mapped[date]
    last_date: Mapped[date]
    next_expected_date: Mapped[date | None]
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    is_subscription: Mapped[bool] = mapped_column(default=False)
    is_salary: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(default="active")
    user_confirmed: Mapped[bool | None]
    updated_at: Mapped[datetime] = updated_at()


class ExpectedTransaction(Base):
    __tablename__ = "expected_transactions"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    pattern_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recurring_patterns.id", ondelete="CASCADE")
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    label: Mapped[str]
    category_key: Mapped[str]
    kind: Mapped[str]
    expected_date: Mapped[date]
    expected_amount: Mapped[Decimal]
    range_min: Mapped[Decimal]
    range_max: Mapped[Decimal]
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    prediction_source: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending")
    matched_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str]
    target_amount: Mapped[Decimal]
    current_amount: Mapped[Decimal] = mapped_column(default=Decimal(0))
    target_date: Mapped[date | None]
    priority: Mapped[int] = mapped_column(default=3)
    minimum_monthly_contribution: Mapped[Decimal] = mapped_column(default=Decimal(0))
    desired_monthly_contribution: Mapped[Decimal] = mapped_column(default=Decimal(0))
    flexibility: Mapped[str] = mapped_column(default="medium")
    linked_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(default="active")
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
