from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from bankboard.api.deps import DB, CurrentUser
from bankboard.api.schemas import ConnectIn, ConnectionOut
from bankboard.core.config import get_settings
from bankboard.core.db import session_scope
from bankboard.events.bus import dispatch_pending
from bankboard.models import BankConnection
from bankboard.providers.base import ProviderError
from bankboard.providers.registry import available_providers, get_provider
from bankboard.services.bank_connections import (
    AuthorizationError,
    complete_connection,
    revoke_connection,
    start_connection,
)
from bankboard.services.sync import sync_connection

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bank", tags=["bank"])


def _redirect_url(provider: str) -> str:
    s = get_settings()
    if provider == "enable_banking":
        return s.enable_banking_redirect_url
    return f"{s.app_base_url.rstrip('/')}/api/bank/callback"


def run_sync_job(connection_id: uuid.UUID) -> None:
    """Background: sync then process events (pipeline, snapshots, detectors)."""
    try:
        with session_scope() as session:
            sync_connection(session, connection_id)
        with session_scope() as session:
            dispatch_pending(session)
    except ProviderError as exc:
        log.warning("background sync failed kind=%s", exc.kind)
    except Exception:
        log.exception("background sync crashed")


@router.get("/providers")
def providers() -> dict[str, object]:
    s = get_settings()
    return {"providers": [
        {"key": p, "configured": (p != "enable_banking" or s.enable_banking_configured)}
        for p in available_providers()]}


@router.get("/institutions")
def institutions(user: CurrentUser, provider: str = "enable_banking", country: str = "FR") -> dict[str, object]:
    try:
        items = get_provider(provider).list_institutions(country)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Provider error ({exc.kind})") from exc
    return {"institutions": [{"name": i.name, "country": i.country, "logo": i.logo} for i in items]}


@router.post("/connect")
def connect(body: ConnectIn, user: CurrentUser, db: DB) -> dict[str, str]:
    try:
        url = start_connection(db, user_id=user.id, provider_key=body.provider,
                               institution_name=body.institution_name,
                               institution_country=body.institution_country,
                               redirect_url=_redirect_url(body.provider))
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Provider error ({exc.kind})") from exc
    return {"url": url}


@router.get("/callback")
def callback(user: CurrentUser, db: DB, background: BackgroundTasks,
             code: Annotated[str | None, Query(max_length=2048)] = None,
             state: Annotated[str | None, Query(max_length=256)] = None,
             error: Annotated[str | None, Query(max_length=200)] = None) -> RedirectResponse:
    front = get_settings().frontend_url.rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{front}/settings?bank=error", status_code=303)
    try:
        connection = complete_connection(db, user_id=user.id, code=code, state=state)
    except AuthorizationError:
        db.commit()  # persist the consumed state
        return RedirectResponse(f"{front}/settings?bank=invalid", status_code=303)
    db.commit()
    background.add_task(run_sync_job, connection.id)
    return RedirectResponse(f"{front}/settings?bank=connected", status_code=303)


@router.get("/connections", response_model=list[ConnectionOut])
def connections(user: CurrentUser, db: DB) -> list[ConnectionOut]:
    rows = db.scalars(select(BankConnection).where(BankConnection.user_id == user.id)
                      .order_by(BankConnection.created_at))
    return [ConnectionOut.model_validate(c, from_attributes=True) for c in rows]


@router.post("/connections/{connection_id}/sync", status_code=202)
def sync(connection_id: uuid.UUID, user: CurrentUser, db: DB, background: BackgroundTasks) -> dict[str, str]:
    c = db.get(BankConnection, connection_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    background.add_task(run_sync_job, c.id)
    return {"status": "scheduled"}


@router.delete("/connections/{connection_id}", status_code=204)
def revoke(connection_id: uuid.UUID, user: CurrentUser, db: DB) -> None:
    try:
        revoke_connection(db, user_id=user.id, connection_id=connection_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND) from exc
