"""Cashflow engine: income, spending, savings rate, category breakdown. Pure (Polars, cents)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import polars as pl
from pydantic import BaseModel

from bankboard.analytics.frames import between, spend_expr
from bankboard.core.money import from_cents
from bankboard.engines.common import DateSpan, ExplainLine, Explanation


class CategoryAmount(BaseModel):
    category_key: str
    amount: Decimal
    share: float
    count: int


class CashflowResult(BaseModel):
    period: DateSpan
    income: Decimal
    expenses: Decimal
    net: Decimal
    invested: Decimal
    refunds: Decimal
    savings_rate: float | None
    by_category: list[CategoryAmount]
    by_kind: dict[str, Decimal]
    explanation: Explanation


def _sum(df: pl.DataFrame, expr: pl.Expr) -> int:
    if df.is_empty():
        return 0
    value = df.select(expr.sum()).item()
    return int(value or 0)


def compute_cashflow(df: pl.DataFrame, start: date, end: date) -> CashflowResult:
    p = between(df, start, end)
    income = _sum(p.filter(pl.col("kind") == "income"), pl.col("amount"))
    refunds = _sum(p.filter(pl.col("kind") == "refund"), pl.col("amount"))
    expenses = _sum(p, spend_expr())  # refunds already netted
    invested = -_sum(p.filter(pl.col("kind") == "investment"), pl.col("amount"))
    net = income - expenses
    rate = round(net / income, 4) if income > 0 else None

    cats: list[CategoryAmount] = []
    if not p.is_empty():
        grouped = (
            p.filter(pl.col("kind").is_in(["consumption", "fee", "debt_payment", "refund"]))
            .group_by("category_key")
            .agg(spend_expr().sum().alias("spend"), pl.len().alias("n"))
            .filter(pl.col("spend") != 0)
            .sort("spend", descending=True)
        )
        for row in grouped.iter_rows(named=True):
            cats.append(CategoryAmount(
                category_key=row["category_key"], amount=from_cents(row["spend"]),
                share=round(row["spend"] / expenses, 4) if expenses > 0 else 0.0, count=row["n"],
            ))
    by_kind = {}
    if not p.is_empty():
        for row in p.group_by("kind").agg(pl.col("amount").sum()).iter_rows(named=True):
            by_kind[row["kind"]] = from_cents(row["amount"])

    lines = [
        ExplainLine(label="Revenus", amount=from_cents(income), op="+", detail="kind = income"),
        ExplainLine(label="Dépenses (remboursements déduits)", amount=from_cents(expenses), op="-",
                    detail="consumption + fee + debt_payment − refund"),
        ExplainLine(label="Épargne nette", amount=from_cents(net), op="="),
        ExplainLine(label="dont investi", amount=from_cents(invested), op="·",
                    detail="les investissements ne sont pas des dépenses"),
    ]
    return CashflowResult(
        period=DateSpan(start=start, end=end), income=from_cents(income), expenses=from_cents(expenses),
        net=from_cents(net), invested=from_cents(invested), refunds=from_cents(refunds), savings_rate=rate,
        by_category=cats, by_kind=by_kind,
        explanation=Explanation(
            method="Somme exacte (centimes) des transactions de la période ; virements internes exclus ; "
                   "taux d'épargne = (revenus − dépenses) / revenus.",
            lines=lines,
        ),
    )


class MonthlyCashflow(BaseModel):
    month: str
    income: Decimal
    expenses: Decimal
    net: Decimal
    invested: Decimal
    savings_rate: float | None


def month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def monthly_cashflow(df: pl.DataFrame, today: date, months: int = 12) -> list[MonthlyCashflow]:
    out: list[MonthlyCashflow] = []
    cursor = today.replace(day=1)
    starts = []
    for _ in range(months):
        starts.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    for s in reversed(starts):
        start, end = month_bounds(s)
        r = compute_cashflow(df, start, min(end, today))
        out.append(MonthlyCashflow(month=start.strftime("%Y-%m"), income=r.income, expenses=r.expenses,
                                   net=r.net, invested=r.invested, savings_rate=r.savings_rate))
    return out


def trailing(df: pl.DataFrame, as_of: date, days: int) -> CashflowResult:
    return compute_cashflow(df, as_of - timedelta(days=days - 1), as_of)


def average_daily_spend(df: pl.DataFrame, as_of: date, days: int = 90, *, essential_only: bool = False,
                        exclude_recurring: bool = True, spending_accounts_only: bool = True) -> Decimal:
    """Average daily variable spending (cents-exact, returned as Decimal euros)."""
    p = between(df, as_of - timedelta(days=days), as_of - timedelta(days=1))
    if spending_accounts_only:
        p = p.filter(pl.col("is_spending_account"))
    if exclude_recurring:
        p = p.filter(~pl.col("recurring"))
    if essential_only:
        p = p.filter(pl.col("is_essential"))
    total = _sum(p, spend_expr())
    return from_cents(total / days) if days else Decimal(0)
