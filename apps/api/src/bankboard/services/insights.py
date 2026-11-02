"""Insight persistence with fingerprint deduplication and lifecycle (new/ongoing/resolved/ignored)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from bankboard.core.clock import utcnow
from bankboard.detectors.base import Detector, InsightDraft
from bankboard.models import FeedItem, Insight
from bankboard.services.context import FinancialContext


def run_detectors(session: Session, ctx: FinancialContext, detectors: Sequence[tuple[str, Detector]]) -> int:
    drafts: list[tuple[str, InsightDraft]] = []
    for module, detector in detectors:
        drafts.extend((module, d) for d in detector(ctx))
    return persist_insights(session, ctx.user.id, drafts, modules={m for m, _ in detectors})


def persist_insights(session: Session, user_id: uuid.UUID, drafts: Sequence[tuple[str, InsightDraft]],
                     *, modules: set[str]) -> int:
    now = utcnow()
    existing = {i.fingerprint: i for i in session.scalars(select(Insight).where(Insight.user_id == user_id))}
    seen: set[str] = set()
    for module, d in drafts:
        if d.fingerprint in seen:
            continue
        seen.add(d.fingerprint)
        ins = existing.get(d.fingerprint)
        if ins is None:
            ins = Insight(id=uuid.uuid4(), user_id=user_id, fingerprint=d.fingerprint, type=d.type, module=module,
                          state="new", first_seen=now, last_seen=now, importance=Decimal("0"),
                          confidence=Decimal("0"), title=d.title)
            session.add(ins)
            if d.priority in {"important", "critical"} or d.section == "opportunity":
                add_feed(session, user_id, type_=f"insight.{d.type}", title=d.title, priority=d.priority,
                         data={"fingerprint": d.fingerprint}, dedup_key=f"insight:{d.fingerprint}")
        elif ins.state == "ignored":
            ins.last_seen = now
            continue
        else:
            if ins.state in {"new", "resolved"} and ins.first_seen.date() < now.date():
                ins.state = "ongoing"
            ins.last_seen = now
            ins.resolved_at = None
        ins.title, ins.section, ins.priority = d.title, d.section, d.priority
        ins.importance = Decimal(str(round(d.importance, 3)))
        ins.confidence = Decimal(str(round(d.confidence, 3)))
        ins.metrics, ins.evidence, ins.suggested_actions = d.metrics, d.evidence, d.suggested_actions
    for fp, ins in existing.items():
        if fp not in seen and ins.module in modules and ins.state in {"new", "ongoing"}:
            ins.state = "resolved"
            ins.resolved_at = now
    session.flush()
    return len(seen)


def add_feed(session: Session, user_id: uuid.UUID, *, type_: str, title: str, priority: str = "info",
             data: dict[str, object] | None = None, dedup_key: str | None = None) -> None:
    stmt = pg_insert(FeedItem).values(id=uuid.uuid4(), user_id=user_id, occurred_at=utcnow(), type=type_,
                                      priority=priority, title=title, data=data or {}, dedup_key=dedup_key)
    session.execute(stmt.on_conflict_do_nothing(index_elements=["user_id", "dedup_key"]))


def active_insights(session: Session, user_id: uuid.UUID, section: str | None = None,
                    limit: int = 5) -> list[Insight]:
    q = select(Insight).where(Insight.user_id == user_id, Insight.state.in_(["new", "ongoing"]))
    if section:
        q = q.where(Insight.section == section)
    rows = list(session.scalars(q))
    rows.sort(key=lambda i: -(float(i.importance) * float(i.confidence)))
    return rows[:limit]
