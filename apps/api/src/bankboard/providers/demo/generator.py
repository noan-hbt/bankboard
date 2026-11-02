"""Deterministic synthetic bank data (Enable Banking wire format).

Every day is generated from an RNG seeded by (seed, day), and story events are positioned relative
to a fixed `anchor` date, so the data for a given day never changes between calls. This makes the
demo exercise the real idempotent sync path.
"""

from __future__ import annotations

import calendar
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

CURRENT = "demo-current"
SAVINGS = "demo-savings"

OWN_NAME = "ALEX MARTIN"
CURRENT_IBAN = "FR7630004000031234567890143"
SAVINGS_IBAN = "FR7630004000039876543210987"

OPENING = {CURRENT: Decimal("2200.00"), SAVINGS: Decimal("4000.00")}

ACCOUNTS: list[dict[str, Any]] = [
    {"uid": CURRENT, "name": "Revolut EUR", "currency": "EUR", "cash_account_type": "CACC",
     "account_id": {"iban": CURRENT_IBAN}},
    {"uid": SAVINGS, "name": "Coffre Épargne", "currency": "EUR", "cash_account_type": "SVGS",
     "account_id": {"iban": SAVINGS_IBAN}},
]


@dataclass
class _Tx:
    account: str
    day: date
    amount: Decimal  # signed
    party: str
    remittance: str
    mcc: str | None = None
    party_iban: str | None = None
    hour: int = 12


def _d(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))


def _month_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _business_day_before(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


class DemoDataset:
    def __init__(self, anchor: date, seed: int = 42) -> None:
        self.anchor = anchor
        self.seed = seed
        self.start = anchor - timedelta(days=365)
        self.raise_from = anchor - timedelta(days=150)
        self.bonus_day = anchor - timedelta(days=62)
        self.spike_from = anchor - timedelta(days=45)
        self.new_sub_from = anchor - timedelta(days=70)

    def _rng(self, day: date, stream: str) -> random.Random:
        return random.Random(f"{self.seed}:{stream}:{day.isoformat()}")

    # ------------------------------------------------------------------
    def _monthly(self, day: date) -> list[_Tx]:
        out: list[_Tx] = []
        y, m = day.year, day.month
        rng = self._rng(day, "monthly")

        salary_day = _business_day_before(_month_day(y, m, 28))
        if day == salary_day:
            amount = 2750 if day >= self.raise_from else 2450
            month_name = ["JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET", "AOUT",
                          "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"][m - 1]
            out.append(_Tx(CURRENT, day, _d(amount), "ACME SAS", f"SALAIRE {month_name} {y}",
                           party_iban="FR7610107001011234567890129", hour=7))
        fixed = [
            (1, -29.99, "BASIC FIT", "Basic-Fit abonnement", "7997"),
            (2, -86.40, "NAVIGO", "Navigo mensuel", "4111"),
            (3, -850.00, "SCI LES TILLEULS", "LOYER", None),
            (4, -11.12, "SPOTIFY", "Spotify P0F4A12", "4899"),
            (5, -45.00, "MUTUELLE GENERALE", "MUTUELLE", None),
            (10, -38.50, "AXA FRANCE", "ASSURANCE HABITATION", None),
            (12, -19.99, "FREE MOBILE", "Free Mobile", "4814"),
            (18, -13.49, "NETFLIX.COM", "Netflix", "4899"),
            (22, -2.99, "APPLE.COM/BILL", "iCloud", "5818"),
        ]
        for dom, amt, party, rem, mcc in fixed:
            if day == _month_day(y, m, dom):
                out.append(_Tx(CURRENT, day, _d(amt), party, rem, mcc, hour=6))
        if day == _month_day(y, m, 15):
            out.append(_Tx(CURRENT, day, _d(-(55 + rng.uniform(0, 22))), "EDF", "EDF ELECTRICITE", "4900", hour=6))
        if day == _month_day(y, m, 8) and day >= self.new_sub_from:
            out.append(_Tx(CURRENT, day, _d(-22.00), "OPENAI", "OPENAI *CHATGPT SUBSCR", "5734", hour=9))
        # savings & investment after salary
        if day == salary_day + timedelta(days=1):
            out.append(_Tx(CURRENT, day, _d(-250), OWN_NAME, "To Coffre Épargne",
                           party_iban=SAVINGS_IBAN, hour=9))
            out.append(_Tx(SAVINGS, day, _d(250), OWN_NAME, "From Revolut EUR",
                           party_iban=CURRENT_IBAN, hour=9))
        if day == salary_day + timedelta(days=2):
            out.append(_Tx(CURRENT, day, _d(-200), "TRADE REPUBLIC", "ETF PEA versement mensuel", hour=10))
        if day == _month_day(y, m, 20) and rng.random() < 0.6:
            out.append(_Tx(CURRENT, day, _d(-40), "DAB BNP PARIS", "RETRAIT DAB", "6011", hour=18))
        return out

    def _daily(self, day: date) -> list[_Tx]:
        rng = self._rng(day, "daily")
        out: list[_Tx] = []
        wd = day.weekday()
        spike = 1.35 if day >= self.spike_from else 1.0

        if rng.random() < (0.22 if wd < 5 else 0.4):
            shop = rng.choice([("CARREFOUR CITY", "5411"), ("LIDL", "5411"), ("MONOPRIX", "5411"),
                               ("FRANPRIX", "5411"), ("PICARD", "5411")])
            out.append(_Tx(CURRENT, day, _d(-rng.uniform(9, 58)), shop[0], f"{shop[0]} PARIS", shop[1],
                           hour=rng.choice([12, 18, 19])))
        if rng.random() < 0.20 * spike:
            resto = rng.choice(["LE PETIT CLER", "PNY BURGER", "SUSHI SHOP", "BISTROT VALOIS", "PIZZA POPOLARE",
                                "MCDONALDS"])
            out.append(_Tx(CURRENT, day, _d(-rng.uniform(13, 42) * spike), resto, resto, "5812",
                           hour=rng.choice([12, 13, 20, 21])))
        if wd == 4 and rng.random() < 0.7:
            out.append(_Tx(CURRENT, day, _d(-rng.uniform(18, 32)), "UBER EATS", "UBER * EATS PENDING", "5814",
                           hour=20))
        if wd < 5 and rng.random() < 0.35:
            out.append(_Tx(CURRENT, day, _d(-rng.uniform(3.4, 6.2)), "STARBUCKS", "STARBUCKS COFFEE", "5814",
                           hour=8))
        if (day - self.start).days % 16 == 0:
            out.append(_Tx(CURRENT, day, _d(-rng.uniform(52, 71)), "TOTALENERGIES", "TOTALENERGIES RELAIS",
                           "5542", hour=17))
        if rng.random() < 0.06:
            out.append(_Tx(CURRENT, day, _d(-rng.uniform(9, 70)), "AMAZON", f"AMZN Mktp FR*{rng.randint(10000, 99999)}",
                           "5399", hour=rng.choice([10, 22, 23])))
        if rng.random() < 0.02:
            store = rng.choice(["DECATHLON", "FNAC", "ZARA", "UNIQLO"])
            out.append(_Tx(CURRENT, day, _d(-rng.uniform(25, 140)), store, store, "5311", hour=15))
        if wd >= 5 and rng.random() < 0.18 * spike:
            out.append(_Tx(CURRENT, day, _d(-rng.uniform(15, 55)), "LE COMPTOIR BAR", "LE COMPTOIR BAR", "5813",
                           hour=23))
        if rng.random() < 0.03:
            out.append(_Tx(CURRENT, day, _d(-rng.uniform(9, 24)), "UBER", "UBER *TRIP", "4121", hour=1))
        if rng.random() < 0.02:
            out.append(_Tx(CURRENT, day, _d(-rng.uniform(8, 30)), "PHARMACIE DU MARCHE", "PHARMACIE", "5912",
                           hour=11))
        return out

    def _story(self, day: date) -> list[_Tx]:
        a = self.anchor
        out: list[_Tx] = []
        events: dict[date, list[_Tx]] = {
            a - timedelta(days=300): [_Tx(CURRENT, a - timedelta(days=300), _d(780), "STUDIO BLEU",
                                          "FACTURE F-2025-014", party_iban="FR7614508000301234567890147")],
            a - timedelta(days=190): [_Tx(CURRENT, a - timedelta(days=190), _d(1150), "STUDIO BLEU",
                                          "FACTURE F-2026-003", party_iban="FR7614508000301234567890147")],
            a - timedelta(days=40): [_Tx(CURRENT, a - timedelta(days=40), _d(640), "AGENCE NOMADE",
                                         "INVOICE 2026-17")],
            self.bonus_day: [_Tx(CURRENT, self.bonus_day, _d(2250), "ACME SAS", "PRIME ANNUELLE",
                                 party_iban="FR7610107001011234567890129")],
            a - timedelta(days=230): [
                _Tx(CURRENT, a - timedelta(days=230), _d(-184.20), "RYANAIR", "RYANAIR", "4511"),
                _Tx(CURRENT, a - timedelta(days=230), _d(-412.00), "AIRBNB", "AIRBNB * HMXYZ", "7011"),
            ],
            a - timedelta(days=95): [
                _Tx(CURRENT, a - timedelta(days=95), _d(-236.80), "RYANAIR", "RYANAIR", "4511"),
                _Tx(CURRENT, a - timedelta(days=95), _d(-640.00), "AIRBNB", "AIRBNB * HMABC", "7011"),
            ],
            a - timedelta(days=88): [_Tx(SAVINGS, a - timedelta(days=88), _d(-500), OWN_NAME,
                                         "To Revolut EUR", party_iban=CURRENT_IBAN),
                                     _Tx(CURRENT, a - timedelta(days=88), _d(500), OWN_NAME,
                                         "From Coffre Épargne", party_iban=SAVINGS_IBAN)],
            a - timedelta(days=120): [_Tx(CURRENT, a - timedelta(days=120), _d(-899.00), "FNAC",
                                          "FNAC MACBOOK", "5732")],
            a - timedelta(days=112): [_Tx(CURRENT, a - timedelta(days=112), _d(45.00), "AMAZON",
                                          "AMAZON REMBOURSEMENT")],
            a - timedelta(days=160): [_Tx(CURRENT, a - timedelta(days=160), _d(25.30), "CPAM PARIS",
                                          "REMBOURSEMENT AMELI")],
            a - timedelta(days=21): [_Tx(CURRENT, a - timedelta(days=21), _d(-129.99), "FNAC", "FNAC PARIS",
                                         "5732", hour=16),
                                     _Tx(CURRENT, a - timedelta(days=21), _d(-129.99), "FNAC", "FNAC PARIS",
                                         "5732", hour=16)],
            a - timedelta(days=9): [_Tx(CURRENT, a - timedelta(days=9), _d(-212.00), "LE GRAND VEFOUR",
                                        "LE GRAND VEFOUR", "5812", hour=21)],
            a - timedelta(days=35): [_Tx(CURRENT, a - timedelta(days=35), _d(-2.50), "REVOLUT",
                                         "FRAIS RETRAIT HORS FORFAIT")],
        }
        out.extend(events.get(day, []))
        return out

    # ------------------------------------------------------------------
    def transactions(self, account: str, start: date, end: date, today: date) -> list[dict[str, Any]]:
        start = max(start, self.start)
        out: list[dict[str, Any]] = []
        day = start
        while day <= min(end, today):
            items = [t for t in self._monthly(day) + self._daily(day) + self._story(day) if t.account == account]
            for idx, t in enumerate(items):
                out.append(self._to_wire(t, idx, pending=day >= today - timedelta(days=1)))
            day += timedelta(days=1)
        return out

    def balance(self, account: str, today: date, *, include_pending: bool) -> Decimal:
        total = OPENING[account]
        for raw in self.transactions(account, self.start, today, today):
            if raw["status"] == "PDNG" and not include_pending:
                continue
            amt = Decimal(raw["transaction_amount"]["amount"])
            total += amt if raw["credit_debit_indicator"] == "CRDT" else -amt
        return total

    def _to_wire(self, t: _Tx, idx: int, *, pending: bool) -> dict[str, Any]:
        credit = t.amount > 0
        party_key = "debtor" if credit else "creditor"
        raw: dict[str, Any] = {
            "transaction_amount": {"currency": "EUR", "amount": str(abs(t.amount))},
            "credit_debit_indicator": "CRDT" if credit else "DBIT",
            "status": "PDNG" if pending else "BOOK",
            "booking_date": t.day.isoformat(),
            "value_date": t.day.isoformat(),
            "transaction_date": f"{t.day.isoformat()}T{t.hour:02d}:{(idx * 7) % 60:02d}:00+00:00",
            party_key: {"name": t.party},
            "remittance_information": [t.remittance],
        }
        if t.party_iban:
            raw[f"{party_key}_account"] = {"iban": t.party_iban}
        if t.mcc:
            raw["merchant_category_code"] = t.mcc
        if not pending:
            raw["entry_reference"] = f"{t.account}-{t.day.isoformat()}-{idx:02d}"
        return raw
