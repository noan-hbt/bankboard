"""Internal transfer detection: own-IBAN counterparties and opposite-amount pairs across own accounts."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from bankboard.models import Account, Transaction

PAIR_WINDOW_DAYS = 3
_TRANSFER_NS = uuid.UUID("6f1c1a52-8a3e-4a53-9f39-1f7d0f5c2b10")
_TRANSFER_HINTS = ("VIREMENT INTERNE", "COFFRE", "POCKET", "VAULT", "EPARGNE")


def _looks_internal(tx: Transaction, own_names: set[str]) -> bool:
    if tx.counterparty_name and tx.counterparty_name.strip().upper() in own_names:
        return True
    label = f" {tx.label_normalized} "
    return any(f" {h} " in label for h in _TRANSFER_HINTS)


def detect_transfers(txs: Sequence[Transaction], accounts: Sequence[Account],
                     own_names: set[str] | None = None) -> dict[uuid.UUID, tuple[uuid.UUID, Decimal]]:
    """Return {transaction_id: (transfer_group_id, confidence)}. Pure: does not mutate."""
    own_names = {n.upper() for n in (own_names or set())}
    own_iban_hashes = {a.iban_hash for a in accounts if a.iban_hash}
    result: dict[uuid.UUID, tuple[uuid.UUID, Decimal]] = {}

    candidates = [t for t in txs if t.transfer_source != "manual" and not t.is_excluded]
    by_amount: dict[Decimal, list[Transaction]] = defaultdict(list)
    for t in candidates:
        by_amount[t.amount].append(t)

    paired: set[uuid.UUID] = set()
    for t in sorted(candidates, key=lambda x: (x.booking_date, str(x.id))):
        if t.amount >= 0 or t.id in paired:
            continue
        best: Transaction | None = None
        for other in by_amount.get(-t.amount, []):
            if other.id in paired or other.account_id == t.account_id:
                continue
            gap = abs((other.booking_date - t.booking_date).days)
            if gap > PAIR_WINDOW_DAYS:
                continue
            if best is None or gap < abs((best.booking_date - t.booking_date).days):
                best = other
        if best is None:
            continue
        strong = (t.counterparty_iban_hash in own_iban_hashes or best.counterparty_iban_hash in own_iban_hashes
                  or _looks_internal(t, own_names) or _looks_internal(best, own_names))
        if not strong:
            continue  # same amount coincidence between accounts without any internal signal
        group = uuid.uuid5(_TRANSFER_NS, f"{min(t.id, best.id)}:{max(t.id, best.id)}")
        conf = Decimal("0.98") if t.booking_date == best.booking_date else Decimal("0.92")
        result[t.id] = (group, conf)
        result[best.id] = (group, conf)
        paired.update({t.id, best.id})

    # single leg towards/from an own account whose other side is not connected
    for t in candidates:
        if t.id in paired:
            continue
        if t.counterparty_iban_hash and t.counterparty_iban_hash in own_iban_hashes:
            result[t.id] = (uuid.uuid5(_TRANSFER_NS, f"single:{t.id}"), Decimal("0.85"))
    return result


def apply_transfers(txs: Sequence[Transaction], accounts: Sequence[Account],
                    own_names: set[str] | None = None) -> dict[uuid.UUID, Decimal]:
    """Set transfer groups (non-manual only). Returns {transaction_id: transfer confidence}."""
    detected = detect_transfers(txs, accounts, own_names)
    confidence: dict[uuid.UUID, Decimal] = {}
    for t in txs:
        if t.transfer_source == "manual":
            if t.transfer_group_id is not None:
                confidence[t.id] = Decimal(1)
            continue
        hit = detected.get(t.id)
        if hit:
            t.transfer_group_id, t.transfer_source = hit[0], "rule"
            confidence[t.id] = hit[1]
        else:
            t.transfer_group_id, t.transfer_source = None, None
    return confidence
