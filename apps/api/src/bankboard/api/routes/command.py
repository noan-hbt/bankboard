from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from bankboard.api.deps import DB, Ctx, CurrentUser
from bankboard.api.schemas import InsightOut, InsightPatch
from bankboard.core.clock import utcnow
from bankboard.engines.cashflow import average_daily_spend, compute_cashflow
from bankboard.engines.safe_to_spend import compute_safe_to_spend
from bankboard.engines.state_score import compute_state_score
from bankboard.engines.timeline import project_liquidity
from bankboard.engines.what_changed import compare_periods, resolve_preset
from bankboard.models import FeedItem, Insight
from bankboard.services.insights import active_insights
from bankboard.services.snapshots import previous_snapshot

router = APIRouter(prefix="/api", tags=["command-center"])


def _insight_out(i: Insight) -> InsightOut:
    return InsightOut(id=i.id, type=i.type, module=i.module, section=i.section, priority=i.priority,
                      importance=float(i.importance), confidence=float(i.confidence), title=i.title,
                      metrics=i.metrics, evidence=i.evidence, suggested_actions=i.suggested_actions,
                      state=i.state, first_seen=i.first_seen, last_seen=i.last_seen)


@router.get("/command-center")
def command_center(ctx: Ctx, db: DB) -> dict[str, Any]:
    t = ctx.today
    cf = compute_cashflow(ctx.df, t - timedelta(days=29), t)
    safe = compute_safe_to_spend(ctx.safe_to_spend_inputs(), "until_next_income")
    score = compute_state_score(ctx.state_inputs(t))
    prev = previous_snapshot(db, ctx.user.id, t - timedelta(days=6))
    salary = ctx.salary_pattern()
    horizon = t + timedelta(days=30)
    upcoming = [e for e in ctx.expected if e.expected_date <= horizon]
    outflows = sum((-e.expected_amount for e in upcoming if e.expected_amount < 0 and e.kind != "transfer"
                    and e.confidence >= Decimal("0.5")), Decimal(0))
    projection = project_liquidity(t, ctx.spending_cash(), ctx.expected_items(),
                                   average_daily_spend(ctx.df, t, 90), 30)
    cur, prv = resolve_preset("30d", t)
    wc = compare_periods(ctx.df, cur, prv, ctx.category_labels, limit=3)
    return {
        "generated_at": utcnow(), "today": t, "data_confidence": ctx.data_confidence,
        "has_data": not ctx.df.is_empty(),
        "now": {
            "spending_cash": ctx.spending_cash(), "liquid_assets": ctx.liquid_assets(),
            "net_worth": ctx.net_worth(),
            "cashflow_30d": {"income": cf.income, "expenses": cf.expenses, "net": cf.net,
                             "savings_rate": cf.savings_rate, "invested": cf.invested},
            "safe_to_spend": safe.model_dump(),
            "financial_state": {"score": score.score, "grade": score.grade,
                                "previous": float(prev.financial_score)
                                if prev and prev.financial_score is not None else None},
        },
        "next": {
            "next_income": {"date": salary.next_expected_date, "amount": salary.mean_amount,
                            "confidence": float(salary.confidence), "label": salary.label} if salary else None,
            "expected_outflows_30d": outflows,
            "events": [{"expected_date": e.expected_date, "label": e.label, "expected_amount": e.expected_amount,
                        "confidence": float(e.confidence), "kind": e.kind,
                        "prediction_source": e.prediction_source} for e in upcoming[:12]],
            "projected_balance_30d": projection.end_balance,
            "lowest": projection.lowest.model_dump(),
        },
        "attention": [_insight_out(i).model_dump() for i in active_insights(db, ctx.user.id, "attention", 5)],
        "opportunities": [_insight_out(i).model_dump() for i in active_insights(db, ctx.user.id, "opportunity", 3)],
        "what_changed": {"headline": wc.headline, "drivers": [d.model_dump() for d in wc.category_drivers[:3]],
                         "period": wc.current.model_dump()},
    }


@router.get("/insights", response_model=list[InsightOut])
def insights(user: CurrentUser, db: DB, section: str | None = None,
             include_resolved: bool = False, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[InsightOut]:
    if include_resolved:
        q = select(Insight).where(Insight.user_id == user.id)
        if section:
            q = q.where(Insight.section == section)
        rows = list(db.scalars(q.order_by(Insight.last_seen.desc()).limit(limit)))
    else:
        rows = active_insights(db, user.id, section, limit)
    return [_insight_out(i) for i in rows]


@router.patch("/insights/{insight_id}", response_model=InsightOut)
def patch_insight(insight_id: uuid.UUID, body: InsightPatch, user: CurrentUser, db: DB) -> InsightOut:
    i = db.get(Insight, insight_id)
    if i is None or i.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    i.state = body.state
    if body.state == "resolved":
        i.resolved_at = utcnow()
    return _insight_out(i)


@router.get("/feed")
def feed(user: CurrentUser, db: DB, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[dict[str, Any]]:
    rows = db.scalars(select(FeedItem).where(FeedItem.user_id == user.id)
                      .order_by(FeedItem.occurred_at.desc()).limit(limit))
    return [{"id": str(f.id), "occurred_at": f.occurred_at, "type": f.type, "priority": f.priority,
             "title": f.title, "data": f.data} for f in rows]
