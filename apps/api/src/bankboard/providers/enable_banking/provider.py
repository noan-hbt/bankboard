"""Enable Banking AIS implementation of BankingProvider.

Flow: GET /aspsps -> POST /auth -> (user redirect) -> POST /sessions -> accounts -> balances/transactions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from bankboard.core.config import Settings, get_settings
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
from bankboard.providers.enable_banking.auth import EnableBankingJWT
from bankboard.providers.enable_banking.parsing import parse_account, parse_balance, parse_transaction

log = logging.getLogger(__name__)

MAX_PAGES = 200

# Enable Banking ErrorCode values meaning the session/consent itself is gone -> user must reconnect.
SESSION_GONE = {"EXPIRED_SESSION", "REVOKED_SESSION", "CLOSED_SESSION", "SESSION_DOES_NOT_EXIST"}
# Application-level refusals: the app is not allowed to do this (not activated, restricted mode...).
ACCESS_REFUSED = {"ACCESS_DENIED", "NO_ACCOUNTS_ADDED", "UNAUTHORIZED_ACCESS"}


class EnableBankingProvider:
    key: ClassVar[str] = "enable_banking"

    def __init__(
        self,
        *,
        app_id: str,
        private_key_pem: str,
        base_url: str = "https://api.enablebanking.com",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._jwt = EnableBankingJWT(app_id, private_key_pem)
        self._client = httpx.Client(base_url=base_url, transport=transport, timeout=timeout)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> EnableBankingProvider:
        s = settings or get_settings()
        if not s.enable_banking_configured:
            raise ProviderError("config", "Enable Banking is not configured")
        return cls(app_id=s.enable_banking_app_id, private_key_pem=s.enable_banking_key_pem(),
                   base_url=s.enable_banking_api_url)

    # -- HTTP -----------------------------------------------------------------
    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                 json: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._jwt.token()}"}
        try:
            response = self._client.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"Enable Banking unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise self._error(response, path)
        if not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"items": data}

    @staticmethod
    def _error(response: httpx.Response, path: str = "") -> ProviderError:
        """Map an Enable Banking ErrorResponse ({message, code, error, detail}) to a ProviderError.

        A 403 is only a consent problem when it concerns an existing session; on /auth or /aspsps it
        means the application itself is refused (e.g. production app in restricted mode).
        """
        status_code = response.status_code
        error_code = ""
        message = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                error_code = str(body.get("error") or "").upper()
                message = str(body.get("message") or "")
        except ValueError:
            pass
        log.warning("enable_banking error status=%s path=%s error=%s message=%s",
                    status_code, path.split("/")[1] if "/" in path else path, error_code[:40], message[:160])
        suffix = f" ({error_code}{': ' + message[:160] if message else ''})" if error_code or message else ""
        code = error_code or None
        session_scoped = path.startswith(("/sessions/", "/accounts/"))
        if status_code == 401:
            return ProviderError("auth", f"Enable Banking authentication failed{suffix}",
                                 status_code=status_code, code=code)
        if error_code in SESSION_GONE or (status_code == 403 and session_scoped and error_code not in ACCESS_REFUSED):
            return ProviderError("consent_expired", f"Bank consent expired or revoked{suffix}",
                                 status_code=status_code, code=code)
        if status_code == 403 or error_code in ACCESS_REFUSED:
            return ProviderError("access_denied", f"Enable Banking refused the request{suffix}",
                                 status_code=status_code, code=code)
        if status_code == 429:
            return ProviderError("rate_limited", f"Enable Banking rate limit reached{suffix}",
                                 status_code=status_code, code=code)
        if status_code >= 500:
            return ProviderError("unavailable", f"Enable Banking unavailable{suffix}",
                                 status_code=status_code, code=code)
        return ProviderError("invalid", f"Enable Banking rejected the request ({status_code}){suffix}",
                             status_code=status_code, code=code)

    # -- BankingProvider ------------------------------------------------------
    def list_institutions(self, country: str) -> list[Institution]:
        data = self._request("GET", "/aspsps", params={"country": country.upper()})
        result: list[Institution] = []
        for item in data.get("aspsps", []):
            result.append(Institution(
                name=str(item["name"]), country=str(item.get("country") or country.upper()),
                logo=item.get("logo"),
                max_consent_days=(item.get("maximum_consent_validity") or 0) // 86400 or None,
                max_history_days=None,
            ))
        return result

    def start_authorization(self, institution: Institution, *, state: str, redirect_url: str,
                            valid_until: datetime) -> AuthorizationStart:
        body = {
            "access": {"valid_until": valid_until.astimezone(UTC).isoformat()},
            "aspsp": {"name": institution.name, "country": institution.country},
            "state": state,
            "redirect_url": redirect_url,
            "psu_type": "personal",
        }
        data = self._request("POST", "/auth", json=body)
        if "url" not in data:
            raise ProviderError("invalid", "Enable Banking /auth response without url")
        return AuthorizationStart(url=str(data["url"]), provider_auth_id=data.get("authorization_id"))

    def complete_authorization(self, code: str) -> ProviderSession:
        data = self._request("POST", "/sessions", json={"code": code})
        access = data.get("access") or {}
        valid_until = datetime.fromisoformat(access["valid_until"]) if access.get("valid_until") else None
        aspsp = data.get("aspsp") or {}
        return ProviderSession(
            session=SessionRef(str(data["session_id"])),
            valid_until=valid_until,
            accounts=[parse_account(a) for a in data.get("accounts", [])],
            institution_name=str(aspsp.get("name") or ""),
            institution_country=str(aspsp.get("country") or ""),
        )

    def get_accounts(self, session: SessionRef) -> list[ProviderAccount]:
        data = self._request("GET", f"/sessions/{session.value}")
        accounts = data.get("accounts_data") or data.get("accounts") or []
        parsed: list[ProviderAccount] = []
        for acc in accounts:
            if isinstance(acc, dict) and "uid" in acc:
                parsed.append(parse_account(acc))
            elif isinstance(acc, str):
                details = self._request("GET", f"/accounts/{acc}/details")
                details.setdefault("uid", acc)
                parsed.append(parse_account(details))
        return parsed

    def get_balances(self, session: SessionRef, account_ref: str) -> list[ProviderBalance]:
        data = self._request("GET", f"/accounts/{account_ref}/balances")
        today = datetime.now(UTC).date()
        return [parse_balance(b, today) for b in data.get("balances", [])]

    def get_transactions(self, session: SessionRef, account_ref: str,
                         date_range: DateRange) -> list[ProviderTransaction]:
        params: dict[str, Any] = {
            "date_from": date_range.start.isoformat(),
            "date_to": date_range.end.isoformat(),
        }
        out: list[ProviderTransaction] = []
        for _ in range(MAX_PAGES):
            data = self._request("GET", f"/accounts/{account_ref}/transactions", params=params)
            out.extend(parse_transaction(t) for t in data.get("transactions", []))
            key = data.get("continuation_key")
            if not key:
                return out
            params = {**params, "continuation_key": key}
        raise ProviderError("invalid", "Too many transaction pages")

    def revoke(self, session: SessionRef) -> None:
        self._request("DELETE", f"/sessions/{session.value}")
