"""Demo provider: same contract and parsing path as Enable Banking, synthetic data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import ClassVar

from bankboard.core.clock import today as clock_today
from bankboard.providers.base import (
    AuthorizationStart,
    DateRange,
    Institution,
    ProviderAccount,
    ProviderBalance,
    ProviderError,
    ProviderSession,
    ProviderTransaction,
    SessionRef,
)
from bankboard.providers.demo.generator import ACCOUNTS, CURRENT, SAVINGS, DemoDataset
from bankboard.providers.enable_banking.parsing import parse_account, parse_transaction


class DemoProvider:
    key: ClassVar[str] = "demo"

    def __init__(self, today: date | None = None) -> None:
        self._today = today

    def _now(self) -> date:
        return self._today or clock_today()

    @staticmethod
    def _dataset(session: SessionRef) -> DemoDataset:
        try:
            prefix, anchor = session.value.split(":", 1)
            assert prefix == "demo"
            return DemoDataset(date.fromisoformat(anchor))
        except (ValueError, AssertionError) as exc:
            raise ProviderError("auth", "Invalid demo session") from exc

    def list_institutions(self, country: str) -> list[Institution]:
        return [Institution(name="Revolut (démo)", country=country.upper(), max_consent_days=180)]

    def start_authorization(self, institution: Institution, *, state: str, redirect_url: str,
                            valid_until: datetime) -> AuthorizationStart:
        sep = "&" if "?" in redirect_url else "?"
        return AuthorizationStart(url=f"{redirect_url}{sep}code=demo-code&state={state}", provider_auth_id=None)

    def complete_authorization(self, code: str) -> ProviderSession:
        if code != "demo-code":
            raise ProviderError("auth", "Invalid demo authorization code")
        session = SessionRef(f"demo:{self._now().isoformat()}")
        return ProviderSession(
            session=session,
            valid_until=datetime.now(UTC) + timedelta(days=180),
            accounts=self.get_accounts(session),
            institution_name="Revolut (démo)",
            institution_country="FR",
        )

    def get_accounts(self, session: SessionRef) -> list[ProviderAccount]:
        self._dataset(session)
        return [parse_account(a) for a in ACCOUNTS]

    def get_balances(self, session: SessionRef, account_ref: str) -> list[ProviderBalance]:
        if account_ref not in {CURRENT, SAVINGS}:
            raise ProviderError("invalid", "Unknown demo account")
        ds, today = self._dataset(session), self._now()
        return [
            ProviderBalance("CLBD", ds.balance(account_ref, today, include_pending=False), "EUR", today),
            ProviderBalance("ITAV", ds.balance(account_ref, today, include_pending=True), "EUR", today),
        ]

    def get_transactions(self, session: SessionRef, account_ref: str,
                         date_range: DateRange) -> list[ProviderTransaction]:
        ds = self._dataset(session)
        raws = ds.transactions(account_ref, date_range.start, date_range.end, self._now())
        return [parse_transaction(r) for r in raws]

    def revoke(self, session: SessionRef) -> None:
        return None
