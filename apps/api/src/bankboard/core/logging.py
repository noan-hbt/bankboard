"""Logging with a redaction filter: no IBANs, tokens or amounts in logs."""

from __future__ import annotations

import logging
import re

_PATTERNS = [
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"), "[IBAN]"),
    (re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+"), "[JWT]"),
    (re.compile(r"-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----", re.S), "[PEM]"),
    (re.compile(r"(?i)(session_id|code|state|token|password)=([^&\s]+)"), r"\1=[REDACTED]"),
]


def redact(message: str) -> str:
    for pattern, repl in _PATTERNS:
        message = pattern.sub(repl, message)
    return message


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.getMessage()))
        record.args = None
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
