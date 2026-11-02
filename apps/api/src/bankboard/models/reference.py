from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from bankboard.models.base import Base, created_at, pk


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str]
    name: Mapped[str]
    parent_key: Mapped[str | None]
    is_essential: Mapped[bool] = mapped_column(default=False)
    default_kind: Mapped[str] = mapped_column(default="consumption")
    color: Mapped[str | None]


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str]
    name: Mapped[str]
    default_category_key: Mapped[str | None]
    source: Mapped[str] = mapped_column(default="auto")
    created_at: Mapped[datetime] = created_at()


class MerchantAlias(Base):
    __tablename__ = "merchant_aliases"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("merchants.id", ondelete="CASCADE"))
    match_type: Mapped[str]
    pattern: Mapped[str]
    priority: Mapped[int] = mapped_column(default=100)


class ClassificationRule(Base):
    __tablename__ = "classification_rules"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(default=100)
    field: Mapped[str]
    match_type: Mapped[str]
    pattern: Mapped[str]
    direction: Mapped[str | None]
    category_key: Mapped[str | None]
    kind: Mapped[str | None]
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.9"))
    is_active: Mapped[bool] = mapped_column(default=True)
