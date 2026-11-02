"""Kind + category classification with confidence and source. Manual always wins."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from bankboard.models import Category, ClassificationRule, Merchant, Transaction
from bankboard.pipeline.matching import matches
from bankboard.pipeline.text import normalize_label

SPENDING_KINDS = {"consumption", "fee", "debt_payment"}


@dataclass(frozen=True)
class Classification:
    kind: str
    kind_confidence: Decimal
    kind_source: str
    category_key: str
    category_confidence: Decimal
    category_source: str


@dataclass(frozen=True)
class RuleView:
    priority: int
    is_user: bool
    field: str
    match_type: str
    pattern: str
    direction: str | None
    category_key: str | None
    kind: str | None
    confidence: Decimal


class Classifier:
    def __init__(self, rules: Sequence[RuleView], categories: dict[str, Category],
                 merchants: dict[uuid.UUID, Merchant],
                 history: dict[uuid.UUID, tuple[str, str | None]]) -> None:
        self.rules = sorted(rules, key=lambda r: (not r.is_user, r.priority))
        self.categories = categories
        self.merchants = merchants
        self.history = history  # merchant_id -> (manual category, manual kind)

    def _rule_match(self, tx: Transaction, *, max_priority: int | None = None,
                    min_priority: int | None = None) -> RuleView | None:
        direction = "in" if tx.amount > 0 else "out"
        merchant = self.merchants.get(tx.merchant_id) if tx.merchant_id else None
        values = {
            "label": tx.label_normalized,
            "merchant": (merchant.key if merchant else ""),
            "mcc": tx.mcc or "",
            "counterparty": normalize_label(tx.counterparty_name),
        }
        for rule in self.rules:
            if max_priority is not None and rule.priority >= max_priority and not rule.is_user:
                continue
            if min_priority is not None and rule.priority < min_priority and not rule.is_user:
                continue
            if rule.direction and rule.direction != direction:
                continue
            if matches(rule.match_type, rule.pattern, values.get(rule.field, "")):
                return rule
        return None

    def _default_kind(self, category_key: str) -> str:
        cat = self.categories.get(category_key)
        return cat.default_kind if cat else "consumption"

    def classify(self, tx: Transaction, *, transfer_confidence: Decimal | None) -> Classification:
        inflow = tx.amount > 0
        if transfer_confidence is not None:
            return Classification("transfer", transfer_confidence, "rule",
                                  "internal_transfer", transfer_confidence, "rule")

        category, cat_conf, cat_source = "uncategorized", Decimal("0.2"), "rule"
        kind: str | None = None
        kind_conf = Decimal("0.5")

        strong = self._rule_match(tx, max_priority=50)
        merchant = self.merchants.get(tx.merchant_id) if tx.merchant_id else None
        hist = self.history.get(tx.merchant_id) if tx.merchant_id else None
        if strong and strong.kind:
            kind, kind_conf = strong.kind, strong.confidence
        if strong and strong.category_key:
            category, cat_conf, cat_source = strong.category_key, strong.confidence, "rule"
        elif hist:
            category, cat_conf, cat_source = hist[0], Decimal("0.85"), "historical"
            if hist[1] and kind is None:
                kind, kind_conf = hist[1], Decimal("0.85")
        elif merchant and merchant.default_category_key:
            category, cat_conf, cat_source = merchant.default_category_key, Decimal("0.88"), "rule"
        else:
            weak = self._rule_match(tx, min_priority=50)
            if weak and weak.category_key:
                category, cat_conf, cat_source = weak.category_key, weak.confidence, "rule"
                if kind is None and weak.kind:
                    kind = weak.kind

        if kind is None:
            kind = self._default_kind(category)
            kind_conf = min(cat_conf, Decimal("0.9")) if category != "uncategorized" else Decimal("0.5")

        # Sign coherence
        if inflow and kind in SPENDING_KINDS:
            if category == "uncategorized":
                kind, category, kind_conf, cat_conf = "income", "other_income", Decimal("0.5"), Decimal("0.4")
            else:
                kind, kind_conf = "refund", min(kind_conf, Decimal("0.8"))  # refund of that category
        elif inflow and kind == "investment":
            kind = "income"  # divestment / dividend treated as income in P0
            category = "other_income"
        elif not inflow and kind in {"income", "refund"}:
            kind = "consumption"
            if category in {"salary", "freelance", "bonus", "other_income", "refund"}:
                category, cat_conf = "uncategorized", Decimal("0.2")
        return Classification(kind, kind_conf, "rule", category, cat_conf, cat_source)


def build_classifier(session: Session, user_id: uuid.UUID, txs: Sequence[Transaction]) -> Classifier:
    rules = [
        RuleView(r.priority, r.user_id is not None, r.field, r.match_type, r.pattern, r.direction,
                 r.category_key, r.kind, r.confidence)
        for r in session.scalars(select(ClassificationRule).where(
            ClassificationRule.is_active.is_(True),
            or_(ClassificationRule.user_id.is_(None), ClassificationRule.user_id == user_id)))
    ]
    categories: dict[str, Category] = {}
    for c in session.scalars(select(Category).where(or_(Category.user_id.is_(None),
                                                        Category.user_id == user_id))):
        if c.user_id is not None or c.key not in categories:
            categories[c.key] = c
    merchants = {m.id: m for m in session.scalars(
        select(Merchant).where(or_(Merchant.user_id.is_(None), Merchant.user_id == user_id)))}

    # Learn from manual corrections: most frequent manual category per merchant.
    votes: dict[uuid.UUID, Counter[tuple[str, str | None]]] = defaultdict(Counter)
    for t in txs:
        if t.merchant_id and t.category_source == "manual":
            votes[t.merchant_id][(t.category_key, t.kind if t.kind_source == "manual" else None)] += 1
    history = {mid: c.most_common(1)[0][0] for mid, c in votes.items()}
    return Classifier(rules, categories, merchants, history)


def apply_classification(classifier: Classifier, txs: Sequence[Transaction],
                         transfer_conf: dict[uuid.UUID, Decimal]) -> None:
    for tx in txs:
        result = classifier.classify(tx, transfer_confidence=transfer_conf.get(tx.id))
        if tx.kind_source != "manual":
            tx.kind, tx.kind_confidence, tx.kind_source = result.kind, result.kind_confidence, result.kind_source
        if tx.category_source != "manual":
            tx.category_key = result.category_key
            tx.category_confidence = result.category_confidence
            tx.category_source = result.category_source
