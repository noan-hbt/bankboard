"""User registration, login and opaque cookie sessions."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankboard.core.clock import utcnow
from bankboard.core.config import get_settings
from bankboard.core.crypto import hash_password, random_token, sha256_hex, verify_password
from bankboard.models import User, UserPreferences, UserSession
from bankboard.services.audit import audit


class AuthError(Exception):
    pass


def register(session: Session, *, email: str, password: str, display_name: str | None) -> User:
    email = email.strip().lower()
    if len(password) < 10:
        raise AuthError("Le mot de passe doit contenir au moins 10 caractères")
    if session.scalars(select(User).where(User.email == email)).first():
        raise AuthError("Un compte existe déjà avec cet email")
    user = User(id=uuid.uuid4(), email=email, password_hash=hash_password(password), display_name=display_name)
    session.add(user)
    session.flush()
    session.add(UserPreferences(user_id=user.id, modules={}, settings={}))
    audit(session, user.id, "user.register")
    return user


def login(session: Session, *, email: str, password: str, user_agent: str | None = None,
          ip: str | None = None) -> tuple[User, str]:
    user = session.scalars(select(User).where(User.email == email.strip().lower())).first()
    if user is None or not verify_password(password, user.password_hash):
        audit(session, None, "login.failed", ip=ip)
        raise AuthError("Identifiants invalides")
    token = random_token(32)
    session.add(UserSession(id=uuid.uuid4(), user_id=user.id, token_hash=sha256_hex(token),
                            expires_at=utcnow() + timedelta(days=get_settings().session_ttl_days),
                            user_agent=(user_agent or "")[:200]))
    audit(session, user.id, "login", ip=ip)
    return user, token


def user_for_token(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    s = session.scalars(select(UserSession).where(UserSession.token_hash == sha256_hex(token))).first()
    if s is None or s.revoked_at is not None or s.expires_at < utcnow():
        return None
    return session.get(User, s.user_id)


def logout(session: Session, token: str | None) -> None:
    if not token:
        return
    s = session.scalars(select(UserSession).where(UserSession.token_hash == sha256_hex(token))).first()
    if s is not None:
        s.revoked_at = utcnow()


def delete_all_data(session: Session, user: User) -> None:
    """Right to erasure: every user-owned row cascades from users."""
    audit(session, None, "data.delete", target=str(user.id))
    session.delete(user)
