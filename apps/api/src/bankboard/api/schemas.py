from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
Kind = Literal["consumption", "transfer", "investment", "income", "refund", "fee", "debt_payment"]


class RegisterIn(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=254)
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=100)


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=254)
    password: str = Field(max_length=200)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    base_currency: str


class ConnectIn(BaseModel):
    provider: str = "enable_banking"
    institution_name: str = "Revolut"
    institution_country: str = Field(default="FR", min_length=2, max_length=2)


class ConnectionOut(BaseModel):
    id: uuid.UUID
    provider: str
    institution_name: str
    status: str
    consent_valid_until: datetime | None
    last_synced_at: datetime | None
    last_error: str | None


class AccountOut(BaseModel):
    id: uuid.UUID
    name: str
    iban_masked: str | None
    currency: str
    account_type: str
    is_liquid: bool
    is_spending: bool
    balance: Decimal | None
    balance_date: date | None
    last_synced_at: datetime | None


class AccountPatch(BaseModel):
    name: str | None = None
    account_type: Literal["checking", "savings", "investment", "credit", "loan", "cash", "other"] | None = None
    is_liquid: bool | None = None
    is_spending: bool | None = None
    is_active: bool | None = None


class TransactionOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    booking_date: date
    status: str
    amount: Decimal
    currency: str
    label: str
    merchant: str | None
    merchant_id: uuid.UUID | None
    kind: str
    kind_confidence: Decimal
    kind_source: str
    category_key: str
    category_confidence: Decimal
    category_source: str
    is_recurring: bool
    is_transfer: bool
    is_excluded: bool
    note: str | None


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    sum_amount: Decimal


class TransactionPatch(BaseModel):
    category_key: str | None = None
    kind: Kind | None = None
    note: str | None = Field(default=None, max_length=500)
    is_excluded: bool | None = None
    apply_to_merchant: bool = False


class GoalIn(BaseModel):
    name: str = Field(max_length=100)
    target_amount: Decimal = Field(gt=0)
    current_amount: Decimal = Decimal(0)
    target_date: date | None = None
    priority: int = Field(default=3, ge=1, le=5)
    minimum_monthly_contribution: Decimal = Decimal(0)
    desired_monthly_contribution: Decimal = Decimal(0)
    flexibility: Literal["low", "medium", "high"] = "medium"
    linked_account_id: uuid.UUID | None = None


class GoalOut(GoalIn):
    id: uuid.UUID
    status: str


class LayoutItem(BaseModel):
    i: str
    widget: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=1, le=20)
    hidden: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class LayoutIn(BaseModel):
    items: list[LayoutItem] = Field(max_length=60)


class PreferencesIn(BaseModel):
    min_buffer: Decimal | None = None
    opportunity_rate: Decimal | None = Field(default=None, ge=0, le=Decimal("0.3"))
    modules: dict[str, bool] | None = None
    notification_min_level: Literal["info", "useful", "important", "critical"] | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    conversation_id: uuid.UUID | None = None


class AskOut(BaseModel):
    conversation_id: uuid.UUID
    answer: str
    provider: str
    tools_used: list[str]
    unverified_numbers: list[str]
    refused: bool


class InsightOut(BaseModel):
    id: uuid.UUID
    type: str
    module: str
    section: str
    priority: str
    importance: float
    confidence: float
    title: str
    metrics: dict[str, Any]
    evidence: list[Any]
    suggested_actions: list[Any]
    state: str
    first_seen: datetime
    last_seen: datetime


class InsightPatch(BaseModel):
    state: Literal["ignored", "resolved", "ongoing"]
