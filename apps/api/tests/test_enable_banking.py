from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.orm import Session

from bankboard.core.logging import redact
from bankboard.models import BankAuthRequest, User
from bankboard.providers.base import DateRange, Institution, ProviderError, SessionRef
from bankboard.providers.enable_banking.parsing import parse_transaction
from bankboard.providers.enable_banking.provider import EnableBankingProvider
from bankboard.services.bank_connections import AuthorizationError, complete_connection

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption()).decode()
APP_ID = "app-123"


def provider(handler: object) -> EnableBankingProvider:
    return EnableBankingProvider(app_id=APP_ID, private_key_pem=PEM,
                                 transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_jwt_signed_rs256_with_kid() -> None:
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json={"aspsps": [{"name": "Revolut", "country": "FR"}]})

    items = provider(handler).list_institutions("fr")
    assert items[0].name == "Revolut"
    token = seen["auth"].removeprefix("Bearer ")
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "RS256" and header["kid"] == APP_ID
    claims = jwt.decode(token, KEY.public_key(), algorithms=["RS256"], audience="api.enablebanking.com")
    assert claims["iss"] == "enablebanking.com" and claims["exp"] - claims["iat"] <= 3600
    assert PEM not in repr(provider(handler)._jwt)


def test_auth_and_session_flow() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/auth":
            body = json.loads(req.content)
            assert body["aspsp"] == {"name": "Revolut", "country": "FR"} and body["state"] == "s1"
            return httpx.Response(200, json={"url": "https://bank/auth", "authorization_id": "a1"})
        assert req.url.path == "/sessions"
        return httpx.Response(200, json={
            "session_id": "sess-1", "access": {"valid_until": "2027-04-01T00:00:00+00:00"},
            "aspsp": {"name": "Revolut", "country": "FR"},
            "accounts": [{"uid": "u1", "account_id": {"iban": "FR761111"}, "currency": "EUR",
                          "cash_account_type": "CACC", "name": "Main"}]})

    p = provider(handler)
    start = p.start_authorization(Institution("Revolut", "FR"), state="s1", redirect_url="https://x/cb",
                                  valid_until=datetime.now(UTC) + timedelta(days=90))
    assert start.url == "https://bank/auth"
    sess = p.complete_authorization("code")
    assert sess.session.value == "sess-1" and sess.accounts[0].ref == "u1"


def test_transactions_pagination_and_parsing() -> None:
    pages = {
        None: {"transactions": [{"entry_reference": "e1", "transaction_amount": {"amount": "12.50", "currency": "EUR"},
                                 "credit_debit_indicator": "DBIT", "status": "BOOK", "booking_date": "2026-10-01",
                                 "creditor": {"name": "SPOTIFY"}, "remittance_information": ["Spotify"],
                                 "merchant_category_code": "4899"}],
               "continuation_key": "k2"},
        "k2": {"transactions": [{"transaction_amount": {"amount": "2450", "currency": "EUR"},
                                 "credit_debit_indicator": "CRDT", "status": "PDNG", "booking_date": "2026-10-28",
                                 "debtor": {"name": "ACME"}, "debtor_account": {"iban": "FR76X"},
                                 "remittance_information": ["SALAIRE"]}]},
    }

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["date_from"] == "2026-09-01"
        return httpx.Response(200, json=pages[req.url.params.get("continuation_key")])

    txs = provider(handler).get_transactions(SessionRef("s"), "u1", DateRange(date(2026, 9, 1), date(2026, 11, 1)))
    assert [t.amount for t in txs] == [Decimal("-12.50"), Decimal("2450")]
    assert txs[0].provider_transaction_id == "e1" and txs[0].mcc == "4899"
    assert txs[1].status == "pending" and txs[1].counterparty_name == "ACME"
    assert txs[1].counterparty_iban == "FR76X"


@pytest.mark.parametrize(("code", "body", "kind"), [
    (401, {}, "auth"), (403, {}, "consent_expired"), (400, {"error": "EXPIRED_SESSION"}, "consent_expired"),
    (429, {}, "rate_limited"), (503, {}, "unavailable"), (422, {}, "invalid"),
])
def test_error_mapping(code: int, body: dict[str, str], kind: str) -> None:
    p = provider(lambda req: httpx.Response(code, json=body))
    with pytest.raises(ProviderError) as exc:
        p.get_balances(SessionRef("s"), "u1")
    assert exc.value.kind == kind


def test_parse_transaction_requires_a_date() -> None:
    with pytest.raises(ProviderError):
        parse_transaction({"transaction_amount": {"amount": "1", "currency": "EUR"}})


class _StubProvider:
    key = "stub"

    def start_authorization(self, *a: object, **k: object) -> object:
        from bankboard.providers.base import AuthorizationStart
        return AuthorizationStart(url="https://bank/auth", provider_auth_id=None)

    def complete_authorization(self, code: str) -> object:
        from bankboard.providers.demo.provider import DemoProvider
        return DemoProvider(today=date(2026, 11, 2)).complete_authorization("demo-code")


def test_callback_state_validation(db: Session, user: User, other_user: User) -> None:
    from bankboard.core.clock import utcnow
    from bankboard.core.crypto import sha256_hex

    def req(state: str, *, expired: bool = False, owner: User = user) -> None:
        db.add(BankAuthRequest(user_id=owner.id, provider="stub", state_hash=sha256_hex(state),
                               institution_name="Revolut", institution_country="FR",
                               expires_at=utcnow() + (timedelta(minutes=-1) if expired else timedelta(minutes=10))))
        db.flush()

    stub = _StubProvider()
    with pytest.raises(AuthorizationError):
        complete_connection(db, user_id=user.id, code="c", state="unknown", provider=stub)  # type: ignore[arg-type]
    req("expired", expired=True)
    with pytest.raises(AuthorizationError, match="expired"):
        complete_connection(db, user_id=user.id, code="c", state="expired", provider=stub)  # type: ignore[arg-type]
    req("foreign", owner=other_user)
    with pytest.raises(AuthorizationError):
        complete_connection(db, user_id=user.id, code="c", state="foreign", provider=stub)  # type: ignore[arg-type]
    req("good")
    conn = complete_connection(db, user_id=user.id, code="c", state="good", provider=stub)  # type: ignore[arg-type]
    assert conn.status == "active"
    with pytest.raises(AuthorizationError, match="already used"):
        complete_connection(db, user_id=user.id, code="c", state="good", provider=stub)  # type: ignore[arg-type]


def test_log_redaction() -> None:
    msg = redact("iban FR7630004000031234567890143 token=abc eyJhbGciOi.eyJzdWIi.sig")
    assert "FR76300" not in msg and "abc" not in msg and "eyJ" not in msg
