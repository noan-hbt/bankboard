from __future__ import annotations

import logging
import uuid
from html import escape
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from bankboard.api.deps import DB, CurrentUser, OptionalUser
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


_HINTS: dict[str, str] = {
    "access_denied": (
        "Enable Banking refuse la demande pour cette application. En production, l'application est en "
        "mode restreint tant que tes propres comptes ne sont pas liés : dans le Control Panel Enable Banking, "
        "ouvre l'application et utilise « Link accounts » avec ton compte Revolut, puis réessaie. "
        "Une application sandbox ne donne accès qu'aux banques de test (Mock ASPSP), pas au vrai Revolut."
    ),
    "auth": ("Authentification Enable Banking refusée : vérifie ENABLE_BANKING_APP_ID et la clé privée "
             "(elles doivent correspondre à la même application)."),
    "config": "Enable Banking n'est pas configuré (ENABLE_BANKING_APP_ID et clé privée manquants).",
    "consent_expired": "Le consentement bancaire a expiré ou a été révoqué : reconnecte la banque.",
    "rate_limited": "Trop de requêtes vers Enable Banking : réessaie dans quelques minutes.",
    "unavailable": "Enable Banking ou la banque est indisponible pour le moment : réessaie plus tard.",
    "invalid": "Enable Banking a rejeté la demande.",
}


def provider_error_detail(exc: ProviderError) -> str:
    """User-facing explanation; includes the provider's error code/message (never secrets)."""
    hint = _HINTS.get(exc.kind, "Erreur du fournisseur bancaire.")
    if exc.code == "WRONG_ASPSP_PROVIDED":
        hint = "Cette banque n'est pas proposée par Enable Banking pour ce pays (ou pas pour cette application)."
    return f"{hint} [{exc.kind}: {exc}]"


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
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, provider_error_detail(exc)) from exc
    return {"institutions": [{"name": i.name, "country": i.country, "logo": i.logo} for i in items]}


@router.post("/connect")
def connect(body: ConnectIn, user: CurrentUser, db: DB) -> dict[str, str]:
    try:
        url = start_connection(db, user_id=user.id, provider_key=body.provider,
                               institution_name=body.institution_name,
                               institution_country=body.institution_country,
                               redirect_url=_redirect_url(body.provider))
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, provider_error_detail(exc)) from exc
    return {"url": url}


_RESULT_PAGES = {
    "connected": ("Banque connectée", "La synchronisation a démarré. Tu peux fermer cette page et revenir dans "
                  "l'app bankboard : tes comptes vont apparaître dans quelques instants."),
    "invalid": ("Lien expiré ou déjà utilisé", "Relance la connexion depuis l'app bankboard (Réglages)."),
    "error": ("Connexion annulée", "La banque n'a pas confirmé l'autorisation. Relance la connexion depuis "
              "l'app bankboard (Réglages)."),
}


def _result_page(result: str) -> HTMLResponse:
    """Shown when the bank returns to a browser without our session (e.g. Safari outside the iOS PWA)."""
    title, text = _RESULT_PAGES[result]
    ok = result == "connected"
    front = escape(get_settings().frontend_url.rstrip("/"))
    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} · bankboard</title>
<style>:root{{color-scheme:light dark;--bg:#f4f4f2;--card:#fcfcfb;--b:#e2e1dc;--t:#0b0b0b;--m:#52514e}}
@media(prefers-color-scheme:dark){{:root{{--bg:#121211;--card:#1a1a19;--b:#2e2e2b;--t:#f0efec;--m:#c3c2b7}}}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--t);
font:16px/1.5 ui-sans-serif,system-ui,-apple-system,sans-serif;padding:16px;box-sizing:border-box}}
.c{{background:var(--card);border:1px solid var(--b);border-radius:14px;padding:28px 24px;max-width:380px;
text-align:center}}.i{{font-size:28px;color:{"#0ca30c" if ok else "#d03b3b"}}}h1{{font-size:20px;margin:8px 0}}
p{{color:var(--m);margin:0 0 16px}}
a{{color:#2a78d6}}</style></head><body><main class="c"><div class="i" aria-hidden="true">{"✓" if ok else "▲"}</div>
<h1>{escape(title)}</h1><p>{escape(text)}</p><a href="{front}/settings">Ouvrir bankboard dans ce navigateur</a>
</main></body></html>"""
    return HTMLResponse(html, headers={"cache-control": "no-store", "referrer-policy": "no-referrer"})


@router.get("/callback", response_model=None)
def callback(user: OptionalUser, db: DB, background: BackgroundTasks,
             code: Annotated[str | None, Query(max_length=2048)] = None,
             state: Annotated[str | None, Query(max_length=256)] = None,
             error: Annotated[str | None, Query(max_length=200)] = None) -> RedirectResponse | HTMLResponse:
    front = get_settings().frontend_url.rstrip("/")

    def done(result: str) -> RedirectResponse | HTMLResponse:
        if user is None:
            return _result_page(result)
        return RedirectResponse(f"{front}/settings?bank={result}", status_code=303)

    if error or not code or not state:
        return done("error")
    try:
        connection = complete_connection(db, user_id=user.id if user else None, code=code, state=state)
    except AuthorizationError:
        db.commit()  # persist the consumed state
        return done("invalid")
    db.commit()
    background.add_task(run_sync_job, connection.id)
    return done("connected")


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
