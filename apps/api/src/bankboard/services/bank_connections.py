"""Bank connection lifecycle: authorization (anti-CSRF state), callback, revoke."""

from __future__ import annotations

import contextlib
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankboard.core.clock import utcnow
from bankboard.core.crypto import encrypt, iban_hash, mask_iban, random_token, sha256_hex
from bankboard.models import Account, BankAuthRequest, BankConnection, BankSession
from bankboard.providers.base import BankingProvider, Institution, ProviderError, SessionRef
from bankboard.providers.registry import get_provider
from bankboard.services.audit import audit

STATE_TTL = timedelta(minutes=15)
DEFAULT_CONSENT_DAYS = 180

_SAVINGS_TYPES = {"savings"}


class AuthorizationError(Exception):
    pass


def _resolve_institution(provider: BankingProvider, name: str, country: str) -> Institution:
    """Use the provider's exact institution name and consent limit when the catalog is reachable.

    Banks reject a consent longer than they support (Revolut: often 90 days), and the name must match
    the provider catalog exactly. Falls back to the requested values if the catalog can't be read.
    """
    try:
        catalog = provider.list_institutions(country)
    except ProviderError:
        return Institution(name=name, country=country)
    wanted = name.casefold().strip()
    for inst in catalog:
        if inst.name.casefold().strip() == wanted:
            return inst
    return Institution(name=name, country=country)


def start_connection(
    session: Session, *, user_id: uuid.UUID, provider_key: str, institution_name: str,
    institution_country: str, redirect_url: str, consent_days: int = DEFAULT_CONSENT_DAYS,
    provider: BankingProvider | None = None,
) -> str:
    provider = provider or get_provider(provider_key)
    state = random_token(32)
    now = utcnow()
    institution = _resolve_institution(provider, institution_name, institution_country.upper())
    if institution.max_consent_days:
        consent_days = min(consent_days, institution.max_consent_days)
    start = provider.start_authorization(
        institution, state=state, redirect_url=redirect_url,
        valid_until=now + timedelta(days=consent_days),
    )
    session.add(BankAuthRequest(
        id=uuid.uuid4(), user_id=user_id, provider=provider_key, state_hash=sha256_hex(state),
        institution_name=institution_name, institution_country=institution_country.upper(),
        provider_auth_id=start.provider_auth_id, created_at=now, expires_at=now + STATE_TTL,
    ))
    audit(session, user_id, "bank.connect.start", target=provider_key,
          metadata={"institution": institution_name})
    session.flush()
    return start.url


def complete_connection(
    session: Session, *, user_id: uuid.UUID, code: str, state: str,
    provider: BankingProvider | None = None,
) -> BankConnection:
    """Validate the callback state, exchange the code and persist the connection."""
    if not code or not state or len(state) > 256:
        raise AuthorizationError("Missing code or state")
    request = session.scalars(
        select(BankAuthRequest).where(BankAuthRequest.state_hash == sha256_hex(state))
        .with_for_update()
    ).first()
    now = utcnow()
    if request is None or request.user_id != user_id:
        raise AuthorizationError("Unknown authorization state")
    if request.consumed_at is not None:
        raise AuthorizationError("Authorization state already used")
    if request.expires_at < now:
        raise AuthorizationError("Authorization state expired")
    request.consumed_at = now

    provider = provider or get_provider(request.provider)
    try:
        result = provider.complete_authorization(code)
    except ProviderError as exc:
        raise AuthorizationError(f"Provider rejected the authorization ({exc.kind})") from exc

    connection = BankConnection(
        id=uuid.uuid4(), user_id=user_id, provider=request.provider,
        institution_name=result.institution_name or request.institution_name,
        institution_country=(result.institution_country or request.institution_country)[:2],
        status="active", consent_valid_until=result.valid_until,
    )
    session.add(connection)
    session.flush()
    session.add(BankSession(id=uuid.uuid4(), connection_id=connection.id,
                            session_ref_enc=encrypt(result.session.value), valid_until=result.valid_until))
    for acc in result.accounts:
        is_savings = acc.account_type in _SAVINGS_TYPES
        session.add(Account(
            id=uuid.uuid4(), user_id=user_id, connection_id=connection.id, provider_account_ref=acc.ref,
            name=acc.name, iban_masked=mask_iban(acc.iban), iban_hash=iban_hash(acc.iban),
            currency=acc.currency, account_type=acc.account_type,
            is_liquid=acc.account_type in {"checking", "savings", "cash"},
            is_spending=not is_savings and acc.account_type in {"checking", "cash"},
        ))
    audit(session, user_id, "bank.connect.complete", target=str(connection.id),
          metadata={"provider": request.provider, "accounts": len(result.accounts)})
    session.flush()
    return connection


def revoke_connection(session: Session, *, user_id: uuid.UUID, connection_id: uuid.UUID) -> None:
    connection = session.get(BankConnection, connection_id)
    if connection is None or connection.user_id != user_id:
        raise LookupError("connection")
    from bankboard.core.crypto import decrypt

    for bs in session.scalars(select(BankSession).where(BankSession.connection_id == connection.id,
                                                        BankSession.revoked_at.is_(None))):
        with contextlib.suppress(ProviderError):  # best effort; local revocation still applies
            get_provider(connection.provider).revoke(SessionRef(decrypt(bs.session_ref_enc)))
        bs.revoked_at = utcnow()
    connection.status = "revoked"
    audit(session, user_id, "bank.revoke", target=str(connection.id))
