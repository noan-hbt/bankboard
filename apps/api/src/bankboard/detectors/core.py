"""P0 detectors. Every number in an insight comes from the context, never from text generation."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import polars as pl

from bankboard.analytics.frames import between, spend_expr
from bankboard.core.clock import utcnow
from bankboard.core.money import fmt_eur, from_cents, q
from bankboard.detectors.base import InsightDraft, priority_for
from bankboard.engines.cashflow import compute_cashflow
from bankboard.services.context import FinancialContext


def _fmt(amount: Decimal) -> str:
    return fmt_eur(amount).replace(",00 €", " €")


def category_spike(ctx: FinancialContext) -> list[InsightDraft]:
    """Variable (non-recurring) category spending, last 30 days vs the 3 previous 30-day months.

    Requires the increase to exceed both +25 % / +40 € and 1.5 standard deviations of the
    baseline months, so ordinary month-to-month noise does not raise an alert.
    """
    t = ctx.today
    variable = ctx.df.filter(~pl.col("recurring") & pl.col("kind").is_in(["consumption", "fee", "refund"]))

    def by_cat(df: pl.DataFrame) -> dict[str, int]:
        if df.is_empty():
            return {}
        g = df.group_by("category_key").agg(spend_expr().sum().alias("s"))
        return {r["category_key"]: int(r["s"]) for r in g.iter_rows(named=True)}

    c = by_cat(between(variable, t - timedelta(days=29), t))
    months = [by_cat(between(variable, t - timedelta(days=30 * k + 29), t - timedelta(days=30 * k)))
              for k in (1, 2, 3)]
    out = []
    for cat, cents in c.items():
        base = [m.get(cat, 0) for m in months]
        avg = sum(base) / 3
        std = (sum((b - avg) ** 2 for b in base) / 3) ** 0.5
        delta = cents - avg
        if avg <= 0 or cat in {"uncategorized", "travel"}:
            continue
        if delta < 4000 or cents < avg * 1.25 or delta < 1.5 * std:
            continue
        pct = delta / avg
        label = ctx.category_labels.get(cat, cat)
        importance = min(1.0, 0.35 + delta / 40000)
        confidence = 0.85 if std < avg * 0.5 else 0.7
        out.append(InsightDraft(
            type="category_spike", fingerprint=f"category_spike:{cat}:{t:%Y-%m}",
            title=f"{label} +{pct * 100:.0f} %", importance=round(importance, 3), confidence=confidence,
            # a spending trend is never "critical" on its own
            section="attention", priority=min(priority_for(importance, confidence), "important",
                                              key=["info", "useful", "important", "critical"].index),
            metrics={"category_key": cat, "current_30d": str(from_cents(cents)),
                     "baseline_monthly": str(from_cents(avg)), "delta": str(from_cents(delta)),
                     "delta_pct": round(pct, 4), "baseline_std": str(from_cents(std))},
            evidence=[{"kind": "period_comparison", "current": [str(t - timedelta(days=29)), str(t)],
                       "baseline": [str(t - timedelta(days=119)), str(t - timedelta(days=30))]}],
            suggested_actions=[{"type": "explore", "label": f"Voir les transactions {label}",
                                "filter": {"category": cat, "days": 30}}],
        ))
    return out


def upcoming_large_outflow(ctx: FinancialContext) -> list[InsightDraft]:
    monthly = compute_cashflow(ctx.df, ctx.today - timedelta(days=89), ctx.today).expenses / 3
    threshold = max(Decimal(60), monthly * Decimal("0.05"))
    out = []
    for e in ctx.expected:
        days = (e.expected_date - ctx.today).days
        if not (0 <= days <= 7) or e.expected_amount >= 0 or -e.expected_amount < threshold:
            continue
        if e.kind == "transfer":
            continue
        conf = float(e.confidence)
        when = "aujourd'hui" if days == 0 else "demain" if days == 1 else f"dans {days} jours"
        importance = min(1.0, 0.4 + float(-e.expected_amount / max(monthly, Decimal(1))))
        out.append(InsightDraft(
            type="upcoming_outflow", fingerprint=f"upcoming:{e.pattern_id}:{e.expected_date}",
            title=f"{e.label} probablement débité {when} ({_fmt(-e.expected_amount)})",
            importance=round(importance, 3), confidence=conf, section="attention",
            priority=priority_for(importance, conf),
            metrics={"expected_date": str(e.expected_date), "expected_amount": str(e.expected_amount),
                     "range_min": str(e.range_min), "range_max": str(e.range_max), "confidence": conf},
            evidence=[{"kind": "recurring_pattern", "pattern_id": str(e.pattern_id)}],
        ))
    return out


def dormant_cash(ctx: FinancialContext) -> list[InsightDraft]:
    """Cash on spending accounts well above 30-day needs + comfort buffer."""
    cash = ctx.spending_cash()
    monthly = compute_cashflow(ctx.df, ctx.today - timedelta(days=89), ctx.today).expenses / 3
    if monthly <= 0:
        return []
    upcoming = sum((-e.amount for e in ctx.expected_items()
                    if e.amount < 0 and e.date <= ctx.today + timedelta(days=30)), Decimal(0))
    comfort = monthly * Decimal("1.0")
    dormant = q(cash - max(upcoming, monthly) - comfort * Decimal("0.5"))
    if dormant < Decimal(300):
        return []
    importance = min(0.8, 0.3 + float(dormant / (monthly * 2)))
    return [InsightDraft(
        type="dormant_cash", fingerprint=f"dormant_cash:{ctx.today:%Y-%m}",
        title=f"{_fmt(dormant)} de cash dormant sur ton compte courant", importance=round(importance, 3),
        confidence=0.75, section="opportunity", priority="useful",
        metrics={"spending_cash": str(cash), "next_30d_outflows": str(q(upcoming)),
                 "monthly_expenses": str(q(monthly)), "dormant": str(dormant)},
        suggested_actions=[{"type": "allocate", "label": "Placer ou mettre de côté", "amount": str(dormant)}],
    )]


def duplicate_charge(ctx: FinancialContext) -> list[InsightDraft]:
    recent = between(ctx.df, ctx.today - timedelta(days=30), ctx.today).filter(
        (pl.col("kind") == "consumption") & (pl.col("amount") <= -2000))
    if recent.is_empty():
        return []
    dupes = recent.group_by(["account_id", "booking_date", "amount", "merchant_id"]).agg(
        pl.len().alias("n"), pl.col("merchant").first(), pl.col("id")).filter(pl.col("n") > 1)
    out = []
    for r in dupes.iter_rows(named=True):
        amt = from_cents(-r["amount"])
        out.append(InsightDraft(
            type="duplicate_charge", fingerprint=f"duplicate:{r['merchant_id']}:{r['booking_date']}:{r['amount']}",
            title=f"Double débit possible : {r['merchant']} {_fmt(amt)} × {r['n']}", importance=0.7,
            confidence=0.6, section="attention", priority=priority_for(0.7, 0.6),
            metrics={"merchant": r["merchant"], "amount": str(amt), "count": r["n"],
                     "date": str(r["booking_date"])},
            evidence=[{"kind": "transactions", "ids": r["id"]}],
            suggested_actions=[{"type": "verify", "label": "Vérifier auprès du marchand"}],
        ))
    return out


def new_recurring(ctx: FinancialContext) -> list[InsightDraft]:
    out = []
    for p in ctx.patterns:
        if p.status != "active" or p.direction != "out" or p.kind not in {"consumption", "fee"}:
            continue
        if (ctx.today - p.first_date).days > 100:
            continue
        monthly = p.mean_amount * Decimal("30.44") / p.period_days
        out.append(InsightDraft(
            type="new_recurring", fingerprint=f"new_recurring:{p.id}",
            title=f"Nouvelle dépense récurrente : {p.label} ({_fmt(-p.mean_amount)} / {p.cadence})",
            importance=0.5, confidence=float(p.confidence), section="attention",
            priority=priority_for(0.5, float(p.confidence)),
            metrics={"pattern_id": str(p.id), "amount": str(p.mean_amount), "cadence": p.cadence,
                     "annual_cost": str(q(-monthly * 12)), "first_date": str(p.first_date)},
            suggested_actions=[{"type": "review_subscription", "label": "Garder ou résilier ?"}],
        ))
    return out


def unusual_amount(ctx: FinancialContext) -> list[InsightDraft]:
    """Recent transaction far above the category's historical distribution (robust: median + 6·MAD)."""
    hist = between(ctx.df, ctx.today - timedelta(days=365), ctx.today - timedelta(days=15)).filter(
        pl.col("kind") == "consumption")
    recent = between(ctx.df, ctx.today - timedelta(days=14), ctx.today).filter(pl.col("kind") == "consumption")
    if hist.is_empty() or recent.is_empty():
        return []
    stats = hist.with_columns((-pl.col("amount")).alias("a")).group_by("category_key").agg(
        pl.col("a").median().alias("med"), pl.len().alias("n"),
        (pl.col("a") - pl.col("a").median()).abs().median().alias("mad"))
    table = {r["category_key"]: r for r in stats.iter_rows(named=True)}
    out = []
    for r in recent.iter_rows(named=True):
        s = table.get(r["category_key"])
        if not s or s["n"] < 8 or r["recurring"]:
            continue
        amount = -r["amount"]
        limit = s["med"] + 6 * max(s["mad"], 100)
        if amount > limit and amount >= 8000:
            out.append(InsightDraft(
                type="unusual_amount", fingerprint=f"unusual:{r['id']}",
                title=f"Dépense inhabituelle : {r['merchant']} {_fmt(from_cents(amount))}",
                importance=0.45, confidence=0.7, section="attention", priority=priority_for(0.45, 0.7),
                metrics={"amount": str(from_cents(amount)), "category_median": str(from_cents(s["med"])),
                         "category_key": r["category_key"], "date": str(r["booking_date"])},
                evidence=[{"kind": "transactions", "ids": [r["id"]]}],
            ))
    return out


def connection_health(ctx: FinancialContext) -> list[InsightDraft]:
    out = []
    now = utcnow()
    for c in ctx.connections:
        if c.status in {"reauth_required", "error"}:
            out.append(InsightDraft(
                type="connection", fingerprint=f"connection:{c.id}:{c.status}",
                title=f"{c.institution_name} : reconnexion nécessaire", importance=0.95, confidence=1.0,
                priority="critical", suggested_actions=[{"type": "reconnect", "connection_id": str(c.id)}]))
        elif c.consent_valid_until and c.consent_valid_until - now < timedelta(days=10):
            out.append(InsightDraft(
                type="consent_expiring", fingerprint=f"consent:{c.id}:{c.consent_valid_until:%Y-%m-%d}",
                title=f"Le consentement {c.institution_name} expire bientôt", importance=0.7, confidence=1.0,
                priority="important", suggested_actions=[{"type": "reconnect", "connection_id": str(c.id)}]))
    return out


CORE_DETECTORS = [category_spike, upcoming_large_outflow, dormant_cash, duplicate_charge, new_recurring,
                  unusual_amount, connection_health]
