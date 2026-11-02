"""Money helpers. Analytics work in integer cents; storage/API use Decimal."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

CENT = Decimal("0.01")


def to_cents(value: Decimal | int | float | str) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def from_cents(cents: int | float) -> Decimal:
    return (Decimal(round(cents)) / 100).quantize(CENT)


def q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)
