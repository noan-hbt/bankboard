"""Analysis orchestration: pipeline -> context -> snapshots -> detectors -> feed -> events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import polars as pl
from sqlalchemy.orm import Session

from bankboard.core.clock import today as clock_today
from bankboard.core.money import from_cents
from bankboard.engines.safe_to_spend import compute_safe_to_spend
from bankboard.engines.state_score import compute_state_score, diff_scores
from bankboard.events.bus import publish
from bankboard.modules.registry import enabled_modules
from bankboard.pipeline.runner import run_pipeline
from bankboard.services.context import build_context
from bankboard.services.insights import add_feed, run_detectors
from bankboard.services.snapshots import previous_snapshot, refresh_snapshots


@dataclass(frozen=True)
class RefreshResult:
    transactions: int
    recurring_patterns: int
    snapshots: int
    insights: int
    score: float


def _eur(value: Decimal) -> str:
    return f"{value:,.0f} €".replace(",", " ")


def refresh_user(session: Session, user_id: uuid.UUID, *, today: date | None = None,
                 backfill_days: int = 365) -> RefreshResult:
    today = today or clock_today()
    pipeline = run_pipeline(session, user_id, today=today)
    ctx = build_context(session, user_id, today)
    prev = previous_snapshot(session, user_id, today)
    snapshots = refresh_snapshots(session, ctx, backfill_days=backfill_days)

    detectors = [(m.key, d) for m in enabled_modules(ctx.prefs) for d in m.detectors]
    insights = run_detectors(session, ctx, detectors)

    score = compute_state_score(ctx.state_inputs(today))
    # Feed: salary received in the last 3 days
    if not ctx.df.is_empty():
        salaries = ctx.df.filter((pl.col("category_key") == "salary") & (pl.col("kind") == "income")
                                 & (pl.col("booking_date") >= today - timedelta(days=3)))
        for r in salaries.iter_rows(named=True):
            add_feed(session, user_id, type_="salary.received", priority="useful",
                     title=f"Salaire détecté +{_eur(from_cents(r['amount']))}",
                     data={"transaction_id": r["id"]}, dedup_key=f"salary:{r['id']}")
            safe = compute_safe_to_spend(ctx.safe_to_spend_inputs(), "until_next_income")
            add_feed(session, user_id, type_="safe_to_spend.updated", priority="useful",
                     title=f"Ton safe-to-spend jusqu'au prochain salaire : {_eur(safe.value)}",
                     dedup_key=f"safe_after_salary:{r['id']}")
            publish(session, user_id, "salary.received", {"transaction_id": r["id"]})
    if prev is not None and prev.financial_score is not None:
        delta = score.score - float(prev.financial_score)
        if abs(delta) >= 3:
            changes = diff_scores(prev.details.get("subscores", []), score.subscores)
            add_feed(session, user_id, type_="financial_state.changed", priority="useful",
                     title=f"Financial State {score.score:.0f}/100 ({delta:+.0f})",
                     data={"changes": [c.model_dump() for c in changes[:3]]},
                     dedup_key=f"state:{today}")
            publish(session, user_id, "financial_state.changed", {"score": score.score, "delta": delta})
    session.flush()
    return RefreshResult(transactions=pipeline.transactions, recurring_patterns=pipeline.recurring_patterns,
                         snapshots=snapshots, insights=insights, score=score.score)
