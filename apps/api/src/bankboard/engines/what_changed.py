"""What Changed engine: compare two periods and decompose net-worth change into flows."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

import polars as pl
from pydantic import BaseModel

from bankboard.analytics.frames import between, spend_expr
from bankboard.core.money import from_cents, q
from bankboard.engines.cashflow import compute_cashflow, month_bounds
from bankboard.engines.common import DateSpan, ExplainLine, Explanation

Preset = Literal["yesterday", "7d", "30d", "mtd", "since_salary", "custom"]


def resolve_preset(preset: Preset, today: date, *, last_salary: date | None = None,
                   previous_salary: date | None = None, start: date | None = None,
                   end: date | None = None) -> tuple[DateSpan, DateSpan]:
    """Return (current, previous) spans of equal length."""
    if preset == "yesterday":
        y = today - timedelta(days=1)
        return DateSpan(start=y, end=y, label="hier"), DateSpan(start=y - timedelta(days=1),
                                                                 end=y - timedelta(days=1), label="avant-hier")
    if preset in ("7d", "30d"):
        n = 7 if preset == "7d" else 30
        cur = DateSpan(start=today - timedelta(days=n - 1), end=today, label=f"{n} derniers jours")
        prev = DateSpan(start=cur.start - timedelta(days=n), end=cur.start - timedelta(days=1),
                        label=f"{n} jours précédents")
        return cur, prev
    if preset == "mtd":
        ms, _ = month_bounds(today)
        pms, pme = month_bounds(ms - timedelta(days=1))
        span = (today - ms).days
        return (DateSpan(start=ms, end=today, label="mois en cours"),
                DateSpan(start=pms, end=min(pms + timedelta(days=span), pme), label="même période le mois dernier"))
    if preset == "since_salary":
        if not last_salary:
            return resolve_preset("30d", today)
        span = (today - last_salary).days
        prev_start = previous_salary or (last_salary - timedelta(days=30))
        return (DateSpan(start=last_salary, end=today, label="depuis le dernier salaire"),
                DateSpan(start=prev_start, end=prev_start + timedelta(days=span),
                         label="même durée après le salaire précédent"))
    if start is None or end is None:
        raise ValueError("custom preset requires start and end")
    n = (end - start).days + 1
    return (DateSpan(start=start, end=end, label="période choisie"),
            DateSpan(start=start - timedelta(days=n), end=start - timedelta(days=1), label="période précédente"))


class Driver(BaseModel):
    key: str
    label: str
    previous: Decimal
    current: Decimal
    delta: Decimal
    delta_pct: float | None
    share_of_change: float  # share of the total same-sign change


class WhatChanged(BaseModel):
    current: DateSpan
    previous: DateSpan
    income_current: Decimal
    income_previous: Decimal
    expenses_current: Decimal
    expenses_previous: Decimal
    expenses_delta: Decimal
    expenses_delta_pct: float | None
    net_current: Decimal
    net_previous: Decimal
    variable_current: Decimal
    variable_previous: Decimal
    variable_delta: Decimal
    variable_delta_pct: float | None
    category_drivers: list[Driver]
    merchant_drivers: list[Driver]
    recurring_drivers: list[Driver]
    top_drivers_share: float
    headline: str
    explanation: Explanation


def _spend_by(df: pl.DataFrame, col: str) -> dict[str, int]:
    if df.is_empty():
        return {}
    g = df.filter(pl.col("kind").is_in(["consumption", "fee", "debt_payment", "refund"])).group_by(col).agg(
        spend_expr().sum().alias("s"))
    return {str(r[col]): int(r["s"]) for r in g.iter_rows(named=True) if r[col] is not None}


def _drivers(prev: dict[str, int], cur: dict[str, int], labels: dict[str, str], total_delta: int,
             limit: int) -> list[Driver]:
    keys = set(prev) | set(cur)
    rows = []
    same_sign_total = sum(
        (cur.get(k, 0) - prev.get(k, 0)) for k in keys
        if (cur.get(k, 0) - prev.get(k, 0)) * (1 if total_delta >= 0 else -1) > 0
    )
    for k in keys:
        p, c = prev.get(k, 0), cur.get(k, 0)
        d = c - p
        if d == 0:
            continue
        share = d / same_sign_total if same_sign_total and d * same_sign_total > 0 else 0.0
        rows.append(Driver(key=k, label=labels.get(k, k), previous=from_cents(p), current=from_cents(c),
                           delta=from_cents(d), delta_pct=round(d / p, 4) if p > 0 else None,
                           share_of_change=round(share, 4)))
    direction = 1 if total_delta >= 0 else -1
    rows.sort(key=lambda r: (-(direction * float(r.delta))))
    return rows[:limit]


def compare_periods(df: pl.DataFrame, current: DateSpan, previous: DateSpan,
                    category_labels: dict[str, str] | None = None, limit: int = 6) -> WhatChanged:
    labels = category_labels or {}
    a = compute_cashflow(df, previous.start, previous.end)
    b = compute_cashflow(df, current.start, current.end)
    delta = b.expenses - a.expenses
    pct = float(delta / a.expenses) if a.expenses > 0 else None
    cur_all, prev_all = between(df, current.start, current.end), between(df, previous.start, previous.end)
    # Variable spending drives the analysis; recurring charges mostly create calendar effects
    # (a rent debited on the 3rd falls in or out of a rolling window) and are reported separately.
    cur_df, prev_df = cur_all.filter(~pl.col("recurring")), prev_all.filter(~pl.col("recurring"))
    var_prev = sum(_spend_by(prev_df, "kind").values())
    var_cur = sum(_spend_by(cur_df, "kind").values())
    var_delta = var_cur - var_prev
    var_pct = var_delta / var_prev if var_prev > 0 else None
    cats = _drivers(_spend_by(prev_df, "category_key"), _spend_by(cur_df, "category_key"), labels,
                    var_delta, limit)
    merchant_names: dict[str, str] = {}
    for frame in (cur_all, prev_all):
        if not frame.is_empty():
            for r in frame.select("merchant_id", "merchant").unique().iter_rows(named=True):
                if r["merchant_id"]:
                    merchant_names[r["merchant_id"]] = r["merchant"]
    merchants = _drivers(_spend_by(prev_df, "merchant_id"), _spend_by(cur_df, "merchant_id"), merchant_names,
                         var_delta, limit)
    rec_prev = _spend_by(prev_all.filter(pl.col("recurring")), "category_key")
    rec_cur = _spend_by(cur_all.filter(pl.col("recurring")), "category_key")
    rec_delta = sum(rec_cur.values()) - sum(rec_prev.values())
    recurring = _drivers(rec_prev, rec_cur, labels, rec_delta, limit)
    top_share = round(sum(d.share_of_change for d in cats[:3] if d.share_of_change > 0), 4)

    if var_delta == 0:
        headline = "Tes dépenses courantes sont stables."
    else:
        verb = "augmenté" if var_delta > 0 else "baissé"
        pct_txt = f" de {abs(var_pct) * 100:.0f} %" if var_pct is not None else ""
        headline = (f"Tes dépenses courantes ont {verb}{pct_txt} "
                    f"({'+' if var_delta > 0 else '−'}{abs(from_cents(var_delta))} €)")
        if cats and cats[0].share_of_change > 0:
            headline += f", surtout {cats[0].label.lower()} ({cats[0].share_of_change * 100:.0f} %)"
        headline += "."

    lines = [ExplainLine(label=f"{d.label}", amount=d.delta, op="+" if d.delta > 0 else "-",
                         detail=f"{d.previous} → {d.current} € · {d.share_of_change * 100:.0f} % de la variation")
             for d in cats[:5]]
    if rec_delta:
        lines.append(ExplainLine(label="Récurrents (effet calendrier inclus)", amount=from_cents(rec_delta),
                                 op="·", detail="loyer, abonnements… selon qu'ils tombent dans la période"))
    return WhatChanged(
        current=current, previous=previous, income_current=b.income, income_previous=a.income,
        expenses_current=b.expenses, expenses_previous=a.expenses, expenses_delta=q(delta),
        expenses_delta_pct=round(pct, 4) if pct is not None else None, net_current=b.net, net_previous=a.net,
        variable_current=from_cents(var_cur), variable_previous=from_cents(var_prev),
        variable_delta=from_cents(var_delta),
        variable_delta_pct=round(var_pct, 4) if var_pct is not None else None,
        category_drivers=cats, merchant_drivers=merchants, recurring_drivers=recurring,
        top_drivers_share=top_share, headline=headline,
        explanation=Explanation(
            method="Dépenses courantes (hors récurrents, remboursements déduits) comparées à une période de même "
                   "durée ; part = contribution à la variation totale de même signe. Les récurrents sont isolés "
                   "car leur date de prélèvement crée des effets de calendrier.",
            lines=lines),
    )


class NetWorthChange(BaseModel):
    start: date
    end: date
    start_value: Decimal
    end_value: Decimal
    change: Decimal
    flows: list[ExplainLine]
    unexplained: Decimal
    headline: str


SUBSCRIPTION_CATEGORIES = {"subscriptions"}


def net_worth_change(df: pl.DataFrame, start: date, end: date, start_value: Decimal, end_value: Decimal,
                     category_labels: dict[str, str] | None = None) -> NetWorthChange:
    """Decompose end − start into flows between (start, end]. The residual is reported, never hidden."""
    p = between(df, start + timedelta(days=1), end)

    def s(expr_df: pl.DataFrame, expr: pl.Expr) -> Decimal:
        return from_cents(int(expr_df.select(expr.sum()).item() or 0)) if not expr_df.is_empty() else Decimal(0)

    income = s(p.filter(pl.col("kind") == "income"), pl.col("amount"))
    subs = s(p.filter(pl.col("category_key").is_in(SUBSCRIPTION_CATEGORIES)), -spend_expr())
    fees = s(p.filter(pl.col("kind") == "fee"), pl.col("amount"))
    consumption = s(p.filter(~pl.col("category_key").is_in(SUBSCRIPTION_CATEGORIES)
                             & pl.col("kind").is_in(["consumption", "debt_payment", "refund"])), pl.col("amount"))
    invested = s(p.filter(pl.col("kind") == "investment"), pl.col("amount"))
    transfers = s(p.filter(pl.col("kind") == "transfer"), pl.col("amount"))
    change = q(end_value - start_value)
    flows = [
        ExplainLine(label="Revenus", amount=income, op="+"),
        ExplainLine(label="Consommation", amount=consumption, op="-"),
        ExplainLine(label="Abonnements", amount=subs, op="-"),
        ExplainLine(label="Frais & impôts", amount=fees, op="-"),
    ]
    if invested:
        flows.append(ExplainLine(label="Investissements (sortis du périmètre suivi)", amount=invested, op="-",
                                 detail="ce n'est pas une perte : l'argent est placé sur un compte non connecté"))
    if transfers:
        flows.append(ExplainLine(label="Virements vers/depuis comptes non suivis", amount=transfers, op="·"))
    explained = income + consumption + subs + fees + invested + transfers
    unexplained = q(change - explained)
    if unexplained:
        flows.append(ExplainLine(label="Écart non expliqué", amount=unexplained, op="·",
                                 detail="soldes vs transactions : données manquantes ou ajustements bancaires"))
    verb = "augmenté" if change >= 0 else "baissé"
    return NetWorthChange(start=start, end=end, start_value=q(start_value), end_value=q(end_value), change=change,
                          flows=flows, unexplained=unexplained,
                          headline=f"Ton patrimoine a {verb} de {abs(change)} €.")
