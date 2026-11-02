"""Provider-agnostic banking contract.

Nothing outside `bankboard.providers` may know about a specific provider's wire format.
Providers are stateless: the session reference is passed explicitly on every call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

TransactionStatus = Literal["booked", "pending"]
ProviderErrorKind = Literal["auth", "consent_expired", "rate_limited", "unavailable", "invalid", "config"]


class ProviderError(RuntimeError):
    def __init__(self, kind: ProviderErrorKind, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("DateRange.start must be <= end")


@dataclass(frozen=True)
class Institution:
    name: str
    country: str
    logo: str | None = None
    max_consent_days: int | None = None
    max_history_days: int | None = None


@dataclass(frozen=True)
class AuthorizationStart:
    url: str
    provider_auth_id: str | None


@dataclass(frozen=True)
class SessionRef:
    """Opaque provider session handle. `value` is a secret: never log it."""

    value: str


@dataclass(frozen=True)
class ProviderAccount:
    ref: str
    name: str
    currency: str
    iban: str | None = None
    account_type: Literal["checking", "savings", "investment", "credit", "loan", "cash", "other"] = "checking"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderSession:
    session: SessionRef
    valid_until: datetime | None
    accounts: list[ProviderAccount]
    institution_name: str
    institution_country: str


@dataclass(frozen=True)
class ProviderBalance:
    balance_type: str
    amount: Decimal
    currency: str
    reference_date: date


@dataclass(frozen=True)
class ProviderTransaction:
    """Canonical transaction as seen by the provider layer (before enrichment)."""

    provider_transaction_id: str | None
    status: TransactionStatus
    booking_date: date
    value_date: date | None
    amount: Decimal  # signed, negative = outflow, in account currency
    currency: str
    label: str
    counterparty_name: str | None
    counterparty_iban: str | None
    mcc: str | None
    remittance: list[str]
    raw: dict[str, Any]
    booked_at: datetime | None = None
    original_amount: Decimal | None = None
    original_currency: str | None = None


@runtime_checkable
class BankingProvider(Protocol):
    key: ClassVar[str]

    def list_institutions(self, country: str) -> list[Institution]: ...

    def start_authorization(
        self, institution: Institution, *, state: str, redirect_url: str, valid_until: datetime
    ) -> AuthorizationStart: ...

    def complete_authorization(self, code: str) -> ProviderSession: ...

    def get_accounts(self, session: SessionRef) -> list[ProviderAccount]: ...

    def get_balances(self, session: SessionRef, account_ref: str) -> list[ProviderBalance]: ...

    def get_transactions(
        self, session: SessionRef, account_ref: str, date_range: DateRange
    ) -> list[ProviderTransaction]: ...

    def revoke(self, session: SessionRef) -> None: ...
