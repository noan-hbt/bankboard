from __future__ import annotations

import pytest

from bankboard.core import crypto
from bankboard.core.config import Settings, get_settings


def test_railway_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "bankboard.up.railway.app")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-x")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/db")
    s = Settings()
    assert s.frontend_url == s.app_base_url == "https://bankboard.up.railway.app"
    assert s.allowed_origins == ["https://bankboard.up.railway.app"]
    assert s.enable_banking_redirect_url == "https://bankboard.up.railway.app/api/bank/callback"
    assert s.is_production and s.llm_provider == "openrouter"
    assert s.database_url.startswith("postgresql+psycopg://")


def test_explicit_values_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "x.up.railway.app")
    monkeypatch.setenv("FRONTEND_URL", "https://money.example.com")
    assert Settings().frontend_url == "https://money.example.com"


def test_passphrase_encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "une-longue-phrase-secrete-de-plus-de-32-caracteres")
    get_settings.cache_clear()
    try:
        assert crypto.decrypt(crypto.encrypt("session-123")) == "session-123"
        monkeypatch.setenv("APP_ENCRYPTION_KEY", "court")
        get_settings.cache_clear()
        with pytest.raises(crypto.CryptoError):
            crypto.encrypt("x")
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
