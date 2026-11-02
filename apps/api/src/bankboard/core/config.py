"""Typed application settings. Secrets are SecretStr and never serialized."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://bankboard:bankboard@localhost:5432/bankboard"
    app_encryption_key: SecretStr = SecretStr("")
    app_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    session_ttl_days: int = 30

    enable_banking_app_id: str = ""
    enable_banking_private_key: SecretStr = SecretStr("")
    enable_banking_private_key_path: str = ""
    enable_banking_env: Literal["sandbox", "production"] = "sandbox"
    enable_banking_redirect_url: str = "http://localhost:8000/api/bank/callback"
    enable_banking_api_url: str = "https://api.enablebanking.com"

    llm_provider: Literal["offline", "openrouter"] = "offline"
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str = "anthropic/claude-opus-5.5"

    @field_validator("database_url", mode="before")
    @classmethod
    def _psycopg_driver(cls, v: object) -> object:
        # Railway / Heroku style URLs -> SQLAlchemy psycopg3 driver
        if isinstance(v, str):
            for prefix in ("postgres://", "postgresql://"):
                if v.startswith(prefix):
                    return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def enable_banking_key_pem(self) -> str:
        """Return the RSA private key PEM. Never log the return value."""
        if self.enable_banking_private_key_path:
            return Path(self.enable_banking_private_key_path).read_text()
        return self.enable_banking_private_key.get_secret_value().replace("\\n", "\n")

    @property
    def enable_banking_configured(self) -> bool:
        return bool(
            self.enable_banking_app_id
            and (self.enable_banking_private_key_path or self.enable_banking_private_key.get_secret_value())
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
