from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from bankboard.models.base import Base, created_at, pk, updated_at


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str]
    password_hash: Mapped[str]
    display_name: Mapped[str | None]
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    timezone: Mapped[str] = mapped_column(default="Europe/Paris")
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str]
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    user_agent: Mapped[str | None]


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    min_buffer: Mapped[Decimal | None]
    opportunity_rate: Mapped[Decimal] = mapped_column(default=Decimal("0.05"))
    modules: Mapped[dict[str, Any]] = mapped_column(default=dict)
    notification_min_level: Mapped[str] = mapped_column(default="important")
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_at: Mapped[datetime] = updated_at()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str]
    target: Mapped[str | None]
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict)
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = created_at()
