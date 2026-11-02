"""Enable Banking wire format -> canonical DTOs. Pure functions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bankboard.providers.base import ProviderAccount, ProviderBalance, ProviderError, ProviderTransaction

_CASH_ACCOUNT_TYPES = {
    "CACC": "checking", "CARD": "credit", "SVGS": "savings", "LOAN": "loan", "CASH": "checking",
    "MOMA": "savings", "ONDP": "savings", "TRAS": "checking", "OTHR": "other",
}


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ProviderError("invalid", "Invalid amount in provider payload") from exc


def _date(value: Any) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def parse_account(raw: dict[str, Any]) -> ProviderAccount:
    account_id = raw.get("account_id") or {}
    iban = account_id.get("iban") if isinstance(account_id, dict) else None
    cash_type = str(raw.get("cash_account_type") or "CACC")
    name = raw.get("name") or raw.get("product") or raw.get("details") or "Compte"
    acct_type = _CASH_ACCOUNT_TYPES.get(cash_type, "other")
    return ProviderAccount(
        ref=str(raw["uid"]),
        name=str(name),
        currency=str(raw.get("currency") or "EUR"),
        iban=iban,
        account_type=acct_type,  # type: ignore[arg-type]
        raw=raw,
    )


def parse_balance(raw: dict[str, Any], fallback_date: date) -> ProviderBalance:
    amount = raw.get("balance_amount") or {}
    return ProviderBalance(
        balance_type=str(raw.get("balance_type") or "OTHR"),
        amount=_decimal(amount.get("amount")),
        currency=str(amount.get("currency") or "EUR"),
        reference_date=_date(raw.get("reference_date")) or fallback_date,
    )


def _party_name(party: Any) -> str | None:
    if isinstance(party, dict) and party.get("name"):
        return str(party["name"])
    return None


def _party_iban(account: Any) -> str | None:
    if isinstance(account, dict) and account.get("iban"):
        return str(account["iban"])
    return None


def parse_transaction(raw: dict[str, Any]) -> ProviderTransaction:
    amount_obj = raw.get("transaction_amount") or {}
    magnitude = abs(_decimal(amount_obj.get("amount")))
    indicator = str(raw.get("credit_debit_indicator") or "DBIT").upper()
    signed = magnitude if indicator == "CRDT" else -magnitude

    if indicator == "CRDT":
        counterparty = _party_name(raw.get("debtor"))
        counterparty_iban = _party_iban(raw.get("debtor_account"))
    else:
        counterparty = _party_name(raw.get("creditor"))
        counterparty_iban = _party_iban(raw.get("creditor_account"))

    remittance = [str(r) for r in (raw.get("remittance_information") or []) if r]
    label = counterparty or (remittance[0] if remittance else None) or raw.get("note") or "Transaction"

    status_raw = str(raw.get("status") or "BOOK").upper()
    status = "pending" if status_raw in {"PDNG", "PENDING", "INFO"} else "booked"

    booking = _date(raw.get("booking_date")) or _date(raw.get("transaction_date")) or _date(raw.get("value_date"))
    if booking is None:
        raise ProviderError("invalid", "Transaction without any date")

    booked_at: datetime | None = None
    if raw.get("transaction_date") and "T" in str(raw.get("transaction_date")):
        booked_at = datetime.fromisoformat(str(raw["transaction_date"]))

    provider_id = raw.get("entry_reference") or raw.get("transaction_id")
    exchange = raw.get("exchange_rate") or {}
    instructed = exchange.get("instructed_amount") if isinstance(exchange, dict) else None

    return ProviderTransaction(
        provider_transaction_id=str(provider_id) if provider_id else None,
        status=status,  # type: ignore[arg-type]
        booking_date=booking,
        value_date=_date(raw.get("value_date")),
        amount=signed,
        currency=str(amount_obj.get("currency") or "EUR"),
        label=str(label),
        counterparty_name=counterparty,
        counterparty_iban=counterparty_iban,
        mcc=str(raw["merchant_category_code"]) if raw.get("merchant_category_code") else None,
        remittance=remittance,
        raw=raw,
        booked_at=booked_at,
        original_amount=_decimal(instructed["amount"]) if instructed and instructed.get("amount") else None,
        original_currency=str(instructed.get("currency")) if instructed and instructed.get("currency") else None,
    )
