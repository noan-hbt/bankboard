"""Safe-to-spend engine.

safe_to_spend = liquid spending cash − upcoming obligations − planned savings/investments
               − required buffer − committed goals − predicted essential variable spending
Expected income is never added (conservative by design).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from bankboard.core.money import q
from bankboard.engines.common import ExplainLine, Explanation

Horizon = Literal["today", "week", "until_next_income", "month"]
HORIZONS: tuple[Horizon, ...] = ("today", "week", "until_next_income", "month")
MIN_CONFIDENCE = Decimal("0.5")
SPENDING_KINDS = {"consumption", "fee", "debt_payment"}


@dataclass(frozen=True)
class ExpectedItem:
    date: date
    amount: Decimal  # signed
    label: str
    kind: str
    confidence: Decimal


@dataclass(frozen=True)
class GoalCommitment:
    name: str
    monthly: Decimal


@dataclass(frozen=True)
class SafeToSpendInputs:
    today: date
    spending_cash: Decimal
    cash_lines: list[tuple[str, Decimal]]
    expected: list[ExpectedItem]
    buffer: Decimal
    buffer_detail: str
    goals: list[GoalCommitment] = field(default_factory=list)
    daily_essential_variable: Decimal = Decimal(0)
    next_income_date: date | None = None
    data_confidence: float = 1.0


class SafeToSpendResult(BaseModel):
    horizon: Horizon
    end_date: date
    days: int
    value: Decimal
    spending_cash: Decimal
    obligations: Decimal
    planned_savings: Decimal
    buffer: Decimal
    goals: Decimal
    predicted_essential: Decimal
    per_day: Decimal
    explanation: Explanation


def horizon_end(h: Horizon, today: date, next_income: date | None) -> date:
    if h == "today":
        return today
    if h == "week":
        return today + timedelta(days=6 - today.weekday())
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    if h == "until_next_income":
        if next_income and next_income > today:
            return next_income - timedelta(days=1)
        return month_end
    return month_end


def compute_safe_to_spend(inp: SafeToSpendInputs, horizon: Horizon) -> SafeToSpendResult:
    end = horizon_end(horizon, inp.today, inp.next_income_date)
    days = (end - inp.today).days + 1
    window = [e for e in inp.expected
              if inp.today <= e.date <= end and e.amount < 0 and e.confidence >= MIN_CONFIDENCE]
    obligations_items = [e for e in window if e.kind in SPENDING_KINDS]
    savings_items = [e for e in window if e.kind in {"transfer", "investment"}]
    obligations = q(sum((-e.amount for e in obligations_items), Decimal(0)))
    planned = q(sum((-e.amount for e in savings_items), Decimal(0)))
    goals = q(sum((g.monthly * Decimal(days) / Decimal("30.44") for g in inp.goals), Decimal(0)))
    predicted = q(inp.daily_essential_variable * days)
    value = q(inp.spending_cash - obligations - planned - inp.buffer - goals - predicted)

    lines: list[ExplainLine] = [
        ExplainLine(label="Solde des comptes de dépense", amount=q(inp.spending_cash), op="+",
                    detail=", ".join(f"{n} {a}" for n, a in inp.cash_lines)),
        ExplainLine(label="Déjà engagé (factures, abonnements, loyer)", amount=obligations, op="-",
                    detail="; ".join(f"{e.date:%d/%m} {e.label} {-e.amount}" for e in obligations_items[:8])
                    or None),
    ]
    if planned:
        lines.append(ExplainLine(label="Épargne & investissements planifiés", amount=planned, op="-",
                                 detail="; ".join(f"{e.date:%d/%m} {e.label} {-e.amount}" for e in savings_items)))
    lines.append(ExplainLine(label="Buffer minimum", amount=q(inp.buffer), op="-", detail=inp.buffer_detail))
    if goals:
        lines.append(ExplainLine(label="Objectifs engagés (prorata)", amount=goals, op="-",
                                 detail=", ".join(g.name for g in inp.goals)))
    lines.append(ExplainLine(label="Dépenses essentielles prévues", amount=predicted, op="-",
                             detail=f"{q(inp.daily_essential_variable)} €/jour × {days} j "
                                    "(courses, carburant, santé… hors récurrents, moyenne 90 j)"))
    lines.append(ExplainLine(label="Safe to spend", amount=value, op="="))

    conf = min(inp.data_confidence,
               float(min((e.confidence for e in window), default=Decimal(1))) if window else 1.0)
    return SafeToSpendResult(
        horizon=horizon, end_date=end, days=days, value=value, spending_cash=q(inp.spending_cash),
        obligations=obligations, planned_savings=planned, buffer=q(inp.buffer), goals=goals,
        predicted_essential=predicted, per_day=q(max(value, Decimal(0)) / days),
        explanation=Explanation(
            method="Solde disponible des comptes de dépense moins tout ce qui est déjà promis jusqu'à la fin de "
                   "l'horizon. Les revenus attendus ne sont jamais ajoutés.",
            lines=lines, confidence=round(conf, 3),
        ),
    )


def compute_all(inp: SafeToSpendInputs) -> list[SafeToSpendResult]:
    return [compute_safe_to_spend(inp, h) for h in HORIZONS]
