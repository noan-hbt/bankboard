from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from bankboard.models.base import Base, created_at, pk, updated_at


class BankAuthRequest(Base):
    __tablename__ = "bank_auth_requests"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str]
    state_hash: Mapped[str]
    institution_name: Mapped[str]
    institution_country: Mapped[str] = mapped_column(String(2))
    provider_auth_id: Mapped[str | None]
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]


class BankConnection(Base):
    __tablename__ = "bank_connections"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str]
    institution_name: Mapped[str]
    institution_country: Mapped[str] = mapped_column(String(2))
    status: Mapped[str] = mapped_column(default="active")
    consent_valid_until: Mapped[datetime | None]
    last_synced_at: Mapped[datetime | None]
    last_error: Mapped[str | None]
    last_error_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class BankSession(Base):
    __tablename__ = "bank_sessions"
    id: Mapped[uuid.UUID] = pk()
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_connections.id", ondelete="CASCADE"))
    session_ref_enc: Mapped[str]
    valid_until: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
    revoked_at: Mapped[datetime | None]


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bank_connections.id", ondelete="SET NULL")
    )
    provider_account_ref: Mapped[str | None]
    name: Mapped[str]
    iban_masked: Mapped[str | None]
    iban_hash: Mapped[str | None]
    currency: Mapped[str] = mapped_column(String(3))
    account_type: Mapped[str] = mapped_column(default="checking")
    is_liquid: Mapped[bool] = mapped_column(default=True)
    is_spending: Mapped[bool] = mapped_column(default=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_synced_booking_date: Mapped[date | None]
    last_synced_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Balance(Base):
    __tablename__ = "balances"
    id: Mapped[uuid.UUID] = pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    balance_type: Mapped[str]
    amount: Mapped[Decimal]
    currency: Mapped[str] = mapped_column(String(3))
    reference_date: Mapped[date]
    fetched_at: Mapped[datetime] = created_at()


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bank_connections.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(default="running")
    started_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None]
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None]
