from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from bankboard.core.crypto import iban_hash
from bankboard.models import Account, BankConnection, Transaction, TransactionRaw, User
from bankboard.pipeline.text import normalize_label
from bankboard.providers.base import ProviderTransaction


def ptx(day: date, amount: str, label: str = "SHOP", *, id: str | None = None, status: str = "booked",
        counterparty: str | None = None, iban: str | None = None, mcc: str | None = None,
        remittance: list[str] | None = None) -> ProviderTransaction:
    return ProviderTransaction(
        provider_transaction_id=id, status=status, booking_date=day, value_date=day,  # type: ignore[arg-type]
        amount=Decimal(amount), currency="EUR", label=counterparty or label, counterparty_name=counterparty,
        counterparty_iban=iban, mcc=mcc, remittance=remittance if remittance is not None else [label],
        raw={"label": label, "amount": amount, "date": day.isoformat(), "id": id, "status": status},
    )


def make_account(db: Session, user: User, *, name: str = "Courant", iban: str | None = None,
                 account_type: str = "checking", spending: bool = True) -> Account:
    conn = BankConnection(id=uuid.uuid4(), user_id=user.id, provider="demo", institution_name="Test",
                          institution_country="FR", status="active")
    db.add(conn)
    db.flush()
    acc = Account(id=uuid.uuid4(), user_id=user.id, connection_id=conn.id, provider_account_ref=name,
                  name=name, currency="EUR", account_type=account_type, iban_hash=iban_hash(iban),
                  is_liquid=True, is_spending=spending)
    db.add(acc)
    db.flush()
    return acc


def add_tx(db: Session, account: Account, day: date, amount: str, label: str, *, mcc: str | None = None,
           counterparty: str | None = None, counterparty_iban: str | None = None,
           status: str = "booked", **extra: Any) -> Transaction:
    raw = TransactionRaw(id=uuid.uuid4(), user_id=account.user_id, account_id=account.id, provider="test",
                         dedup_key=f"t:{uuid.uuid4()}", status=status, payload={}, payload_hash="x")
    db.add(raw)
    db.flush()
    t = Transaction(id=uuid.uuid4(), user_id=account.user_id, account_id=account.id, raw_id=raw.id,
                    status=status, booking_date=day, amount=Decimal(amount), currency="EUR", label=label,
                    label_normalized=normalize_label(f"{counterparty or ''} {label}"),
                    counterparty_name=counterparty, counterparty_iban_hash=iban_hash(counterparty_iban), mcc=mcc,
                    **extra)
    db.add(t)
    db.flush()
    return t
