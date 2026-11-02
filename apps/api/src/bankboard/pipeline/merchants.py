"""Merchant resolution: normalized label -> merchant, via aliases, else auto-created merchant."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from bankboard.models import Merchant, MerchantAlias, Transaction
from bankboard.pipeline.matching import matches
from bankboard.pipeline.text import display_name, merchant_key, normalize_label


class MerchantResolver:
    def __init__(self, session: Session, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id
        aliases = list(session.scalars(
            select(MerchantAlias).where(or_(MerchantAlias.user_id.is_(None), MerchantAlias.user_id == user_id))
        ))
        # user aliases first, then most specific (longest) pattern, then priority
        aliases.sort(key=lambda a: (a.user_id is None, -len(a.pattern), a.priority))
        self.aliases = aliases
        self.merchants: dict[uuid.UUID, Merchant] = {
            m.id: m for m in session.scalars(
                select(Merchant).where(or_(Merchant.user_id.is_(None), Merchant.user_id == user_id))
            )
        }
        self.by_key: dict[str, Merchant] = {}
        for m in self.merchants.values():
            # user-scoped merchant wins over global with the same key
            if m.user_id is not None or m.key not in self.by_key:
                self.by_key[m.key] = m

    def resolve_label(self, label_normalized: str, counterparty: str | None) -> tuple[Merchant, str]:
        cp = normalize_label(counterparty)
        for alias in self.aliases:
            if matches(alias.match_type, alias.pattern, cp) or matches(alias.match_type, alias.pattern,
                                                                       label_normalized):
                return self.merchants[alias.merchant_id], "alias"
        basis = cp or label_normalized
        key = merchant_key(basis)
        merchant = self.by_key.get(key)
        if merchant is None:
            merchant = Merchant(id=uuid.uuid4(), user_id=self.user_id, key=key, name=display_name(basis),
                                source="auto")
            self.session.add(merchant)
            self.session.flush()  # no ORM relationship: persist before transactions reference it
            self.merchants[merchant.id] = merchant
            self.by_key[key] = merchant
        return merchant, "auto"


def resolve_merchants(session: Session, user_id: uuid.UUID, txs: Sequence[Transaction]) -> MerchantResolver:
    resolver = MerchantResolver(session, user_id)
    for tx in txs:
        if tx.merchant_source == "manual":
            continue
        merchant, source = resolver.resolve_label(tx.label_normalized, tx.counterparty_name)
        tx.merchant_id = merchant.id
        tx.merchant_source = source
    session.flush()
    return resolver
