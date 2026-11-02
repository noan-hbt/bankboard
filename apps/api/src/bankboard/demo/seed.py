"""Demo mode: a user connected to the demo provider through the real connection + sync path."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankboard.events.bus import dispatch_pending
from bankboard.models import User
from bankboard.providers.demo.provider import DemoProvider
from bankboard.services import auth
from bankboard.services.bank_connections import complete_connection, start_connection
from bankboard.services.sync import sync_connection


def connect_demo(session: Session, user: User, *, today: date | None = None) -> None:
    provider = DemoProvider(today=today)
    url = start_connection(session, user_id=user.id, provider_key="demo", institution_name="Revolut (démo)",
                           institution_country="FR", redirect_url="http://localhost/api/bank/callback",
                           provider=provider)
    state = url.split("state=", 1)[1]
    conn = complete_connection(session, user_id=user.id, code="demo-code", state=state, provider=provider)
    session.commit()
    sync_connection(session, conn.id, provider=provider, today=today)
    dispatch_pending(session)


def seed_demo_user(session: Session, *, email: str, password: str) -> User:
    user = session.scalars(select(User).where(User.email == email)).first()
    if user is None:
        user = auth.register(session, email=email, password=password, display_name="Alex Martin")
        session.commit()
    connect_demo(session, user)
    return user
