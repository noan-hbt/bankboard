from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from bankboard.models.base import Base, created_at, pk, updated_at


class FinancialSnapshot(Base):
    __tablename__ = "financial_snapshots"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    snapshot_date: Mapped[date]
    net_worth: Mapped[Decimal]
    liquid_assets: Mapped[Decimal]
    cash: Mapped[Decimal]
    investments: Mapped[Decimal] = mapped_column(default=Decimal(0))
    liabilities: Mapped[Decimal] = mapped_column(default=Decimal(0))
    monthly_income: Mapped[Decimal]
    monthly_expenses: Mapped[Decimal]
    savings_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    safe_to_spend: Mapped[Decimal | None]
    financial_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    goal_progress: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    data_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    is_reconstructed: Mapped[bool] = mapped_column(default=False)
    computed_at: Mapped[datetime] = created_at()


class DomainEvent(Base):
    __tablename__ = "domain_events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    occurred_at: Mapped[datetime] = created_at()
    processed_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None]


class Insight(Base):
    __tablename__ = "insights"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    fingerprint: Mapped[str]
    type: Mapped[str]
    module: Mapped[str]
    section: Mapped[str] = mapped_column(default="attention")
    priority: Mapped[str] = mapped_column(default="useful")
    importance: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    title: Mapped[str]
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    evidence: Mapped[list[Any]] = mapped_column(default=list)
    suggested_actions: Mapped[list[Any]] = mapped_column(default=list)
    state: Mapped[str] = mapped_column(default="new")
    first_seen: Mapped[datetime] = created_at()
    last_seen: Mapped[datetime] = created_at()
    resolved_at: Mapped[datetime | None]


class FeedItem(Base):
    __tablename__ = "feed_items"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    occurred_at: Mapped[datetime] = created_at()
    type: Mapped[str]
    priority: Mapped[str] = mapped_column(default="info")
    title: Mapped[str]
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    dedup_key: Mapped[str | None]


class DashboardLayout(Base):
    __tablename__ = "dashboard_layouts"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(default="default")
    layout: Mapped[list[Any]]
    updated_at: Mapped[datetime] = updated_at()


class AdvisorConversation(Base):
    __tablename__ = "advisor_conversations"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None]
    created_at: Mapped[datetime] = created_at()


class AdvisorMessage(Base):
    __tablename__ = "advisor_messages"
    id: Mapped[uuid.UUID] = pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("advisor_conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str]
    content: Mapped[str]
    tool_calls: Mapped[list[Any]] = mapped_column(default=list)
    provider: Mapped[str | None]
    created_at: Mapped[datetime] = created_at()
