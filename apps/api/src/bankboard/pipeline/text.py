"""Label normalization (pure, deterministic)."""

from __future__ import annotations

import re
import unicodedata

_NOISE_PREFIXES = re.compile(
    r"^(PAIEMENT PAR CARTE|PAIEMENT CB|PRLV SEPA|PRELEVEMENT SEPA|PRELEVEMENT|PRLV|CARTE|CB|VIR SEPA|"
    r"VIREMENT SEPA|VIR INST|VIR|PAYMENT|CARD PAYMENT|POS)\b\s*"
)
_DATE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}([/.-]\d{2,4})?\b")
_SEPARATORS = re.compile(r"[*_#/\\|:;,.'\"()\[\]{}]+")
_HAS_DIGIT = re.compile(r"\d")
_SPACES = re.compile(r"\s+")
_STOPWORDS = {"SA", "SAS", "SARL", "EU", "FR", "LTD", "GMBH", "INC", "THE", "DE", "LA", "LE", "DU", "DES", "WWW",
              "COM", "MKTP", "MARKETPLACE", "PAYMENTS", "SERVICES", "FRANCE", "PARIS", "S", "X"}


def strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def normalize_label(value: str | None) -> str:
    """'Paiement par carte AMZN Mktp FR*AB123 12/10' -> 'AMZN MKTP FR'."""
    if not value:
        return ""
    s = strip_accents(value).upper()
    s = _DATE.sub(" ", s)
    s = _SEPARATORS.sub(" ", s)
    s = _SPACES.sub(" ", s).strip()
    for _ in range(2):
        s = _NOISE_PREFIXES.sub("", s).strip()
    tokens = [t for t in s.split(" ") if t and not _HAS_DIGIT.search(t)]
    return " ".join(tokens)


def merchant_key(normalized: str) -> str:
    tokens = [t for t in normalized.split(" ") if t not in _STOPWORDS and len(t) > 1]
    return "-".join(tokens[:3]).lower() or normalized.lower().replace(" ", "-")[:40] or "unknown"


def display_name(normalized: str) -> str:
    tokens = [t for t in normalized.split(" ") if t not in _STOPWORDS and len(t) > 1][:3]
    return " ".join(t.capitalize() for t in tokens) or normalized.title() or "Inconnu"
