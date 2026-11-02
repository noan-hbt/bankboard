"""System reference data: categories, merchants, aliases, rules.

Idempotent upsert by natural key; safe to re-run (used by migration 0002 and `jobs seed-reference`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from bankboard.models import Category, ClassificationRule, Merchant, MerchantAlias


@dataclass(frozen=True)
class CategoryDef:
    key: str
    name: str
    parent: str | None = None
    essential: bool = False
    kind: str = "consumption"
    color: str | None = None


CATEGORIES: list[CategoryDef] = [
    CategoryDef("housing", "Logement", essential=True, color="#6366f1"),
    CategoryDef("utilities", "Énergie & télécom", essential=True, color="#0ea5e9"),
    CategoryDef("insurance", "Assurances", essential=True, color="#14b8a6"),
    CategoryDef("groceries", "Courses", essential=True, color="#22c55e"),
    CategoryDef("transport", "Transports", essential=True, color="#f59e0b"),
    CategoryDef("fuel", "Carburant", parent="transport", essential=True, color="#d97706"),
    CategoryDef("health", "Santé", essential=True, color="#ef4444"),
    CategoryDef("taxes", "Impôts", essential=True, kind="fee", color="#64748b"),
    CategoryDef("restaurants", "Restaurants", color="#f97316"),
    CategoryDef("food_delivery", "Livraison repas", parent="restaurants", color="#fb923c"),
    CategoryDef("coffee", "Cafés", parent="restaurants", color="#a16207"),
    CategoryDef("bars", "Bars & sorties", color="#e11d48"),
    CategoryDef("shopping", "Shopping", color="#8b5cf6"),
    CategoryDef("online_shopping", "Achats en ligne", parent="shopping", color="#a855f7"),
    CategoryDef("subscriptions", "Abonnements", color="#ec4899"),
    CategoryDef("entertainment", "Loisirs", color="#06b6d4"),
    CategoryDef("travel", "Voyages", color="#3b82f6"),
    CategoryDef("personal_care", "Soins", color="#f472b6"),
    CategoryDef("gifts", "Cadeaux", color="#facc15"),
    CategoryDef("education", "Formation", color="#84cc16"),
    CategoryDef("fees", "Frais bancaires", kind="fee", color="#94a3b8"),
    CategoryDef("cash", "Retraits", color="#78716c"),
    CategoryDef("salary", "Salaire", kind="income", color="#10b981"),
    CategoryDef("freelance", "Freelance", kind="income", color="#34d399"),
    CategoryDef("bonus", "Primes", kind="income", color="#6ee7b7"),
    CategoryDef("other_income", "Autres revenus", kind="income", color="#a7f3d0"),
    CategoryDef("refund", "Remboursements", kind="refund", color="#5eead4"),
    CategoryDef("investment", "Investissements", kind="investment", color="#4f46e5"),
    CategoryDef("internal_transfer", "Virements internes", kind="transfer", color="#9ca3af"),
    CategoryDef("debt", "Crédits", essential=True, kind="debt_payment", color="#475569"),
    CategoryDef("uncategorized", "Non classé", color="#cbd5e1"),
]

# (key, display name, default category, aliases [(match_type, pattern)])
MERCHANTS: list[tuple[str, str, str, list[tuple[str, str]]]] = [
    ("amazon", "Amazon", "online_shopping", [("prefix", "AMZN"), ("contains", "AMAZON")]),
    ("spotify", "Spotify", "subscriptions", [("contains", "SPOTIFY")]),
    ("netflix", "Netflix", "subscriptions", [("contains", "NETFLIX")]),
    ("disney-plus", "Disney+", "subscriptions", [("contains", "DISNEY PLUS"), ("contains", "DISNEYPLUS")]),
    ("apple", "Apple", "subscriptions", [("contains", "APPLE COM BILL"), ("prefix", "APPLE")]),
    ("uber-eats", "Uber Eats", "food_delivery", [("contains", "UBER EATS"), ("contains", "UBEREATS")]),
    ("deliveroo", "Deliveroo", "food_delivery", [("contains", "DELIVEROO")]),
    ("uber", "Uber", "transport", [("prefix", "UBER")]),
    ("bolt", "Bolt", "transport", [("prefix", "BOLT")]),
    ("mcdonalds", "McDonald's", "restaurants", [("contains", "MCDONALD"), ("contains", "MC DONALD")]),
    ("starbucks", "Starbucks", "coffee", [("contains", "STARBUCKS")]),
    ("carrefour", "Carrefour", "groceries", [("contains", "CARREFOUR")]),
    ("lidl", "Lidl", "groceries", [("contains", "LIDL")]),
    ("monoprix", "Monoprix", "groceries", [("contains", "MONOPRIX")]),
    ("franprix", "Franprix", "groceries", [("contains", "FRANPRIX")]),
    ("leclerc", "E.Leclerc", "groceries", [("contains", "LECLERC")]),
    ("auchan", "Auchan", "groceries", [("contains", "AUCHAN")]),
    ("picard", "Picard", "groceries", [("contains", "PICARD")]),
    ("totalenergies", "TotalEnergies", "fuel", [("contains", "TOTALENERGIES"), ("contains", "TOTAL ACCESS")]),
    ("shell", "Shell", "fuel", [("prefix", "SHELL")]),
    ("esso", "Esso", "fuel", [("prefix", "ESSO")]),
    ("sncf", "SNCF", "transport", [("contains", "SNCF")]),
    ("ratp", "RATP", "transport", [("contains", "RATP")]),
    ("navigo", "Navigo", "transport", [("contains", "NAVIGO")]),
    ("free-mobile", "Free Mobile", "utilities", [("contains", "FREE MOBILE")]),
    ("orange", "Orange", "utilities", [("prefix", "ORANGE")]),
    ("edf", "EDF", "utilities", [("prefix", "EDF")]),
    ("engie", "Engie", "utilities", [("contains", "ENGIE")]),
    ("airbnb", "Airbnb", "travel", [("contains", "AIRBNB")]),
    ("booking", "Booking.com", "travel", [("contains", "BOOKING COM")]),
    ("ryanair", "Ryanair", "travel", [("contains", "RYANAIR")]),
    ("decathlon", "Decathlon", "shopping", [("contains", "DECATHLON")]),
    ("fnac", "Fnac", "shopping", [("contains", "FNAC")]),
    ("axa", "AXA", "insurance", [("prefix", "AXA")]),
    ("maif", "MAIF", "insurance", [("contains", "MAIF")]),
    ("pharmacie", "Pharmacie", "health", [("prefix", "PHARMACIE"), ("prefix", "PHARMA")]),
    ("basic-fit", "Basic-Fit", "subscriptions", [("contains", "BASIC FIT"), ("contains", "BASICFIT")]),
    ("openai", "OpenAI", "subscriptions", [("contains", "OPENAI")]),
]

# (priority, field, match_type, pattern, direction, category_key, kind, confidence)
RULES: list[tuple[int, str, str, str, str | None, str | None, str | None, str]] = [
    (10, "label", "contains", "SALAIRE", "in", "salary", "income", "0.97"),
    (10, "label", "contains", "SALARY", "in", "salary", "income", "0.97"),
    (10, "label", "contains", "PAYROLL", "in", "salary", "income", "0.95"),
    (12, "label", "contains", "PRIME", "in", "bonus", "income", "0.9"),
    (12, "label", "contains", "BONUS", "in", "bonus", "income", "0.9"),
    (12, "label", "contains", "FACTURE", "in", "freelance", "income", "0.8"),
    (12, "label", "contains", "INVOICE", "in", "freelance", "income", "0.8"),
    # kind-only rules: the category comes from the merchant (an Amazon refund reduces online shopping)
    (15, "label", "contains", "REMBOURSEMENT", "in", None, "refund", "0.9"),
    (15, "label", "contains", "REFUND", "in", None, "refund", "0.9"),
    (14, "label", "contains", "AMELI", "in", "health", "refund", "0.9"),
    (14, "label", "contains", "CPAM", "in", "health", "refund", "0.9"),
    (20, "label", "contains", "LOYER", "out", "housing", "consumption", "0.95"),
    (20, "label", "contains", "RENT", "out", "housing", "consumption", "0.85"),
    (20, "label", "contains", "ASSURANCE", "out", "insurance", "consumption", "0.85"),
    (20, "label", "contains", "MUTUELLE", "out", "insurance", "consumption", "0.9"),
    (20, "label", "contains", "DGFIP", "out", "taxes", "fee", "0.95"),
    (20, "label", "contains", "IMPOT", "out", "taxes", "fee", "0.9"),
    (20, "label", "contains", "ECHEANCE PRET", "out", "debt", "debt_payment", "0.9"),
    (20, "label", "contains", "CREDIT IMMO", "out", "debt", "debt_payment", "0.9"),
    (25, "label", "contains", "FRAIS", "out", "fees", "fee", "0.85"),
    (25, "label", "contains", "FEE", "out", "fees", "fee", "0.8"),
    (25, "label", "contains", "COMMISSION", "out", "fees", "fee", "0.85"),
    (30, "label", "contains", "RETRAIT", "out", "cash", "consumption", "0.9"),
    (30, "label", "contains", "ATM", "out", "cash", "consumption", "0.85"),
    (30, "label", "contains", "CASH WITHDRAWAL", "out", "cash", "consumption", "0.9"),
    (35, "label", "contains", "TRADING", "out", "investment", "investment", "0.85"),
    (35, "label", "contains", "ETF", "out", "investment", "investment", "0.85"),
    (35, "label", "contains", "BOURSE", "out", "investment", "investment", "0.85"),
    (35, "label", "contains", "PEA", "out", "investment", "investment", "0.75"),
    (18, "label", "contains", "ASSURANCE VIE", "out", "investment", "investment", "0.85"),
    (35, "label", "contains", "CRYPTO", "out", "investment", "investment", "0.75"),
    # ISO 18245 merchant category codes
    (50, "mcc", "exact", "5411", None, "groceries", None, "0.85"),
    (50, "mcc", "exact", "5812", None, "restaurants", None, "0.85"),
    (50, "mcc", "exact", "5814", None, "restaurants", None, "0.8"),
    (50, "mcc", "exact", "5813", None, "bars", None, "0.8"),
    (50, "mcc", "exact", "5541", None, "fuel", None, "0.9"),
    (50, "mcc", "exact", "5542", None, "fuel", None, "0.9"),
    (50, "mcc", "exact", "4111", None, "transport", None, "0.85"),
    (50, "mcc", "exact", "4121", None, "transport", None, "0.85"),
    (50, "mcc", "exact", "4131", None, "transport", None, "0.85"),
    (50, "mcc", "exact", "4511", None, "travel", None, "0.85"),
    (50, "mcc", "exact", "7011", None, "travel", None, "0.85"),
    (50, "mcc", "exact", "5912", None, "health", None, "0.85"),
    (50, "mcc", "exact", "4814", None, "utilities", None, "0.8"),
    (50, "mcc", "exact", "5311", None, "shopping", None, "0.7"),
    (50, "mcc", "exact", "5399", None, "shopping", None, "0.7"),
    (50, "mcc", "exact", "5732", None, "shopping", None, "0.75"),
    (50, "mcc", "exact", "6011", None, "cash", None, "0.9"),
    (50, "mcc", "exact", "7997", None, "entertainment", None, "0.7"),
    (50, "mcc", "exact", "7832", None, "entertainment", None, "0.8"),
]


def ensure_reference_data(session: Session) -> None:
    existing_cats = {c.key: c for c in session.scalars(select(Category).where(Category.user_id.is_(None)))}
    for cd in CATEGORIES:
        cat = existing_cats.get(cd.key)
        if cat is None:
            cat = Category(user_id=None, key=cd.key)
            session.add(cat)
        cat.name, cat.parent_key, cat.is_essential = cd.name, cd.parent, cd.essential
        cat.default_kind, cat.color = cd.kind, cd.color

    existing_merchants = {
        m.key: m for m in session.scalars(select(Merchant).where(Merchant.user_id.is_(None)))
    }
    existing_aliases = {
        (a.match_type, a.pattern)
        for a in session.scalars(select(MerchantAlias).where(MerchantAlias.user_id.is_(None)))
    }
    for key, name, category, aliases in MERCHANTS:
        merchant = existing_merchants.get(key)
        if merchant is None:
            merchant = Merchant(user_id=None, key=key, name=name, source="seed")
            session.add(merchant)
            session.flush()
        merchant.name, merchant.default_category_key = name, category
        for match_type, pattern in aliases:
            if (match_type, pattern) not in existing_aliases:
                prio = 10 if match_type == "exact" else 50 if match_type == "prefix" else 100
                session.add(MerchantAlias(user_id=None, merchant_id=merchant.id, match_type=match_type,
                                          pattern=pattern, priority=prio))

    existing_rules = {
        (r.field, r.match_type, r.pattern, r.direction)
        for r in session.scalars(select(ClassificationRule).where(ClassificationRule.user_id.is_(None)))
    }
    for prio, field, match_type, pattern, direction, rule_category, kind, conf in RULES:
        if (field, match_type, pattern, direction) in existing_rules:
            continue
        session.add(ClassificationRule(
            user_id=None, priority=prio, field=field, match_type=match_type, pattern=pattern,
            direction=direction, category_key=rule_category, kind=kind, confidence=Decimal(conf),
        ))
    session.flush()
