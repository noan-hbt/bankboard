from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://bankboard:bankboard@localhost:5432/bankboard_test")
os.environ["APP_ENV"] = "test"
os.environ.setdefault("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ["LLM_PROVIDER"] = "offline"

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from bankboard.core.crypto import hash_password
from bankboard.core.db import get_engine, new_session
from bankboard.models import User

API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = date(2026, 11, 2)


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> Iterator[None]:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(API_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(API_DIR, "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture()
def db() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
    finally:
        session.rollback()
        # row-level cascade (not TRUNCATE ... CASCADE) keeps global reference data
        session.execute(text("DELETE FROM domain_events; DELETE FROM audit_logs; DELETE FROM users"))
        session.commit()
        session.close()


@pytest.fixture()
def user(db: Session) -> User:
    u = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@test.local", password_hash=hash_password("pw-123456"),
             display_name="Alex Martin")
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def other_user(db: Session) -> User:
    u = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@test.local", password_hash="x")
    db.add(u)
    db.commit()
    return u
