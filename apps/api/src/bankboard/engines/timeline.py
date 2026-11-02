"""Expected financial timeline and day-by-day liquidity projection."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel

from bankboard.core.money import q
from bankboard.engines.common import ExplainLine, Explanation
from bankboard.engines.safe_to_spend import ExpectedItem


class TimelineEvent(BaseModel):
    expected_date: date
    label: str
    kind: str
    expected_amount: Decimal
    range_min: Decimal
    range_max: Decimal
    confidence: float
    prediction_source: str
    category_key: str


class DayPoint(BaseModel):
    date: date
    balance: Decimal
    inflow: Decimal
    outflow: Decimal
    pressure: float  # 0..1 share of the horizon's outflows happening that day


class LiquidityProjection(BaseModel):
    start_balance: Decimal
    days: list[DayPoint]
    lowest: DayPoint
    end_balance: Decimal
    explanation: Explanation


def project_liquidity(today: date, start_balance: Decimal, expected: list[ExpectedItem],
                      daily_variable: Decimal, days: int = 30) -> LiquidityProjection:
    by_day: dict[date, list[ExpectedItem]] = {}
    for e in expected:
        if today <= e.date < today + timedelta(days=days) and e.confidence >= Decimal("0.5"):
            by_day.setdefault(e.date, []).append(e)
    total_out = sum((-e.amount for es in by_day.values() for e in es if e.amount < 0), Decimal(0))
    total_out += daily_variable * days
    balance = start_balance
    points: list[DayPoint] = []
    for i in range(days):
        d = today + timedelta(days=i)
        items = by_day.get(d, [])
        inflow = sum((e.amount for e in items if e.amount > 0), Decimal(0))
        outflow = sum((-e.amount for e in items if e.amount < 0), Decimal(0)) + daily_variable
        balance = balance + inflow - outflow
        points.append(DayPoint(date=d, balance=q(balance), inflow=q(inflow), outflow=q(outflow),
                               pressure=round(float(outflow / total_out), 4) if total_out else 0.0))
    lowest = min(points, key=lambda p: p.balance) if points else DayPoint(
        date=today, balance=q(start_balance), inflow=Decimal(0), outflow=Decimal(0), pressure=0.0)
    return LiquidityProjection(
        start_balance=q(start_balance), days=points, lowest=lowest,
        end_balance=points[-1].balance if points else q(start_balance),
        explanation=Explanation(
            method="Solde actuel + événements attendus (confiance ≥ 50 %) − dépense variable moyenne quotidienne.",
            lines=[
                ExplainLine(label="Solde de départ", amount=q(start_balance), op="+"),
                ExplainLine(label="Dépense variable estimée / jour", amount=q(daily_variable), op="-",
                            detail="moyenne 90 j hors récurrents"),
                ExplainLine(label="Point bas attendu", amount=lowest.balance, op="=",
                            detail=lowest.date.isoformat()),
            ],
        ),
    )
