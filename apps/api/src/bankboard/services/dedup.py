"""Deterministic deduplication keys for provider transactions."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from bankboard.providers.base import ProviderTransaction


def fingerprint(tx: ProviderTransaction) -> str:
    parts = [
        tx.status,
        tx.booking_date.isoformat(),
        f"{tx.amount:.4f}",
        tx.currency,
        (tx.counterparty_name or "").strip().upper(),
        "|".join(r.strip().upper() for r in tx.remittance),
        tx.label.strip().upper(),
    ]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:40]


def dedup_keys(transactions: list[ProviderTransaction]) -> list[str]:
    """Provider id when available, otherwise content fingerprint + occurrence rank.

    The occurrence rank keeps two genuinely identical transactions (two coffees, same day, same
    price) distinct, and is reproducible as long as sync windows always cover whole days.
    """
    seen: Counter[str] = Counter()
    keys: list[str] = []
    for tx in transactions:
        if tx.provider_transaction_id:
            keys.append(f"id:{tx.provider_transaction_id}")
            continue
        fp = fingerprint(tx)
        keys.append(f"fp:{fp}#{seen[fp]}")
        seen[fp] += 1
    return keys


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
