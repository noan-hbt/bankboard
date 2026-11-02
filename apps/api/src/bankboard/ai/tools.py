"""Typed internal tools exposed to the LLM. All values come from deterministic engines."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import polars as pl
from sqlalchemy.orm import Session

from bankboard.ai.base import ToolSpec
from bankboard.analytics.frames import between, spend_expr
from bankboard.core.money import from_cents
from bankboard.engines.cashflow import compute_cashflow
from bankboard.engines.safe_to_spend import compute_all
from bankboard.engines.state_score import compute_state_score
from bankboard.engines.what_changed import Preset, compare_periods, resolve_preset
from bankboard.services.context import FinancialContext
from bankboard.services.insights import active_insights

MAX_ROWS = 50
PRESETS = {"yesterday", "7d", "30d", "mtd", "since_salary", "custom"}


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _out(obj: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = _jsonable(obj)
    return result


def _date(value: Any, default: date) -> date:
    try:
        return date.fromisoformat(str(value)) if value else default
    except ValueError:
        return default


def build_tools(session: Session, ctx: FinancialContext) -> list[ToolSpec]:
    t = ctx.today

    def get_financial_state(_: dict[str, Any]) -> dict[str, Any]:
        score = compute_state_score(ctx.state_inputs(t))
        cf = compute_cashflow(ctx.df, t - timedelta(days=29), t)
        return _out({
            "today": t, "net_worth": ctx.net_worth(), "liquid_assets": ctx.liquid_assets(),
            "spending_cash": ctx.spending_cash(),
            "last_30_days": {"income": cf.income, "expenses": cf.expenses, "net": cf.net,
                             "savings_rate": cf.savings_rate, "invested": cf.invested},
            "financial_state_score": score.score, "grade": score.grade,
            "subscores": [{"label": s.label, "score": s.score, "metric": s.metric} for s in score.subscores],
            "data_confidence": ctx.data_confidence,
        })

    def get_safe_to_spend(_: dict[str, Any]) -> dict[str, Any]:
        return _out({"horizons": [
            {"horizon": r.horizon, "until": r.end_date, "safe_to_spend": r.value, "per_day": r.per_day,
             "breakdown": [{"label": ln.label, "amount": ln.amount} for ln in r.explanation.lines]}
            for r in compute_all(ctx.safe_to_spend_inputs())]})

    def compare(args: dict[str, Any]) -> dict[str, Any]:
        preset_raw = str(args.get("preset") or "30d")
        preset: Preset = preset_raw if preset_raw in PRESETS else "30d"  # type: ignore[assignment]
        if preset == "custom":
            cur, prev = resolve_preset("custom", t, start=_date(args.get("start"), t - timedelta(days=29)),
                                       end=_date(args.get("end"), t))
        else:
            dates = ctx.salary_dates()
            cur, prev = resolve_preset(preset, t, last_salary=dates[-1] if dates else None,
                                       previous_salary=dates[-2] if len(dates) > 1 else None)
        if args.get("previous_start") and args.get("previous_end"):
            from bankboard.engines.common import DateSpan
            prev = DateSpan(start=_date(args["previous_start"], prev.start), end=_date(args["previous_end"], prev.end))
        wc = compare_periods(ctx.df, cur, prev, ctx.category_labels)
        return _out(wc.model_dump(exclude={"explanation"}))

    def query_transactions(args: dict[str, Any]) -> dict[str, Any]:
        start = _date(args.get("start"), t - timedelta(days=365))
        end = _date(args.get("end"), t)
        df = between(ctx.df, start, end)
        if args.get("search"):
            s = str(args["search"]).lower()
            df = df.filter(pl.col("merchant").str.to_lowercase().str.contains(s, literal=True)
                           | pl.col("label").str.to_lowercase().str.contains(s, literal=True))
        if args.get("category"):
            df = df.filter(pl.col("category_key") == args["category"])
        if args.get("kind"):
            df = df.filter(pl.col("kind") == args["kind"])
        total_spend = int(df.select(spend_expr().sum()).item() or 0) if not df.is_empty() else 0
        total_in = int(df.filter(pl.col("amount") > 0)["amount"].sum() or 0) if not df.is_empty() else 0
        by_month = []
        if not df.is_empty():
            g = (df.with_columns(pl.col("booking_date").dt.strftime("%Y-%m").alias("m")).group_by("m")
                 .agg(spend_expr().sum().alias("s"), pl.len().alias("n")).sort("m"))
            by_month = [{"month": r["m"], "spending": from_cents(r["s"]), "count": r["n"]}
                        for r in g.iter_rows(named=True)]
        rows = df.sort("booking_date", descending=True).head(MAX_ROWS)
        return _out({
            "period": {"start": start, "end": end}, "count": df.height,
            "total_spending": from_cents(total_spend), "total_inflows": from_cents(total_in),
            "by_month": by_month,
            "transactions": [{"date": r["booking_date"], "merchant": r["merchant"], "amount": from_cents(r["amount"]),
                              "category": r["category_key"], "kind": r["kind"]} for r in rows.iter_rows(named=True)],
            "truncated": df.height > MAX_ROWS,
        })

    def query_metrics(args: dict[str, Any]) -> dict[str, Any]:
        start = _date(args.get("start"), t - timedelta(days=29))
        end = _date(args.get("end"), t)
        cf = compute_cashflow(ctx.df, start, end)
        return _out(cf.model_dump(exclude={"explanation"}) | {
            "category_labels": {c.category_key: ctx.category_labels.get(c.category_key, c.category_key)
                                for c in cf.by_category}})

    def get_predictions(args: dict[str, Any]) -> dict[str, Any]:
        days = int(args.get("days") or 30)
        return _out({"events": [
            {"date": e.expected_date, "label": e.label, "amount": e.expected_amount, "range_min": e.range_min,
             "range_max": e.range_max, "confidence": float(e.confidence), "source": e.prediction_source}
            for e in ctx.expected if e.expected_date <= t + timedelta(days=days)][:60]})

    def get_insights(_: dict[str, Any]) -> dict[str, Any]:
        return _out({"insights": [
            {"title": i.title, "type": i.type, "section": i.section, "importance": float(i.importance),
             "confidence": float(i.confidence), "metrics": i.metrics}
            for i in active_insights(session, ctx.user.id, limit=10)]})

    def get_recurring(_: dict[str, Any]) -> dict[str, Any]:
        return _out({"patterns": [
            {"label": p.label, "cadence": p.cadence, "amount": p.mean_amount, "category": p.category_key,
             "is_subscription": p.is_subscription, "next": p.next_expected_date, "confidence": float(p.confidence),
             "annual_cost": p.mean_amount * Decimal("365.25") / p.period_days}
            for p in ctx.patterns if p.status == "active"]})

    date_prop = {"type": "string", "description": "ISO date YYYY-MM-DD"}
    return [
        ToolSpec("get_financial_state", "Current snapshot: net worth, cash, last-30-day cashflow, Financial State "
                 "Score with sub-scores, data confidence.", {"type": "object", "properties": {}}, get_financial_state),
        ToolSpec("get_safe_to_spend", "Safe-to-spend for today / this week / until next income / this month, with "
                 "the full breakdown.", {"type": "object", "properties": {}}, get_safe_to_spend),
        ToolSpec("compare_periods", "Explain what changed in spending between two periods (drivers by category "
                 "and merchant, recurring separated).", {"type": "object", "properties": {
                     "preset": {"type": "string", "enum": ["yesterday", "7d", "30d", "mtd", "since_salary", "custom"]},
                     "start": date_prop, "end": date_prop, "previous_start": date_prop, "previous_end": date_prop}},
                 compare),
        ToolSpec("query_transactions", "Search transactions with aggregates (total spending, inflows, monthly "
                 "breakdown); returns at most 50 rows.", {"type": "object", "properties": {
                     "start": date_prop, "end": date_prop,
                     "search": {"type": "string", "description": "merchant or label substring"},
                     "category": {"type": "string"}, "kind": {"type": "string"}}}, query_transactions),
        ToolSpec("query_metrics", "Cashflow metrics for a period: income, expenses, savings rate, categories.",
                 {"type": "object", "properties": {"start": date_prop, "end": date_prop}}, query_metrics),
        ToolSpec("get_predictions", "Expected future transactions with amount range and confidence.",
                 {"type": "object", "properties": {"days": {"type": "integer"}}}, get_predictions),
        ToolSpec("get_insights", "Active prioritized insights (attention and opportunities).",
                 {"type": "object", "properties": {}}, get_insights),
        ToolSpec("get_recurring", "Recurring payments, subscriptions and income patterns.",
                 {"type": "object", "properties": {}}, get_recurring),
    ]
