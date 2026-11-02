"""Application-level encryption for secrets stored at rest (e.g. bank session ids)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet

from bankboard.core.config import get_settings


class CryptoError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().app_encryption_key.get_secret_value()
    if not key:
        raise CryptoError("APP_ENCRYPTION_KEY is not configured")
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=32
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def mask_iban(iban: str | None) -> str | None:
    if not iban:
        return None
    clean = iban.replace(" ", "")
    return f"{clean[:4]}••••{clean[-4:]}" if len(clean) > 8 else "••••"


def iban_hash(iban: str | None) -> str | None:
    if not iban:
        return None
    return sha256_hex(iban.replace(" ", "").upper())
