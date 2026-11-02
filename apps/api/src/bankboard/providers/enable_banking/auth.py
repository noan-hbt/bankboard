"""Enable Banking application authentication: RS256-signed JWT, backend only."""

from __future__ import annotations

import threading
import time

import jwt

TOKEN_TTL_SECONDS = 3600
REFRESH_MARGIN_SECONDS = 60


class EnableBankingJWT:
    """Builds and caches the application JWT. The private key never leaves this object."""

    def __init__(self, app_id: str, private_key_pem: str) -> None:
        if not app_id or not private_key_pem:
            raise ValueError("Enable Banking app id and private key are required")
        self._app_id = app_id
        self._key = private_key_pem
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def __repr__(self) -> str:  # never expose the key
        return f"EnableBankingJWT(app_id={self._app_id!r})"

    def token(self) -> str:
        with self._lock:
            now = time.time()
            if self._token is None or now >= self._expires_at - REFRESH_MARGIN_SECONDS:
                iat = int(now)
                payload = {
                    "iss": "enablebanking.com",
                    "aud": "api.enablebanking.com",
                    "iat": iat,
                    "exp": iat + TOKEN_TTL_SECONDS,
                }
                headers = {"typ": "JWT", "alg": "RS256", "kid": self._app_id}
                self._token = jwt.encode(payload, self._key, algorithm="RS256", headers=headers)
                self._expires_at = float(iat + TOKEN_TTL_SECONDS)
            return self._token
