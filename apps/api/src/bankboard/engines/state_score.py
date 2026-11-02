"""Financial State Score (0–100): weighted, explainable sub-scores."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from bankboard.engines.common import ExplainLine, Explanation


def piecewise(x: float, points: list[tuple[float, float]]) -> float:
    """Linear interpolation over sorted (x, y) points, clamped at both ends."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in itertools.pairwise(points):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


@dataclass(frozen=True)
class StateInputs:
    liquid_assets: Decimal
    essential_monthly: Decimal
    total_monthly_expenses: Decimal
    savings_rate_3m: float | None
    income_cv: float | None
    spend_ratio: float | None  # last 30d variable spending / previous 90d monthly average
    goal_progress: float | None
    data_confidence: float


class SubScore(BaseModel):
    key: str
    label: str
    score: float
    weight: float
    points: float  # contribution to total
    metric: str
    detail: str


class StateScore(BaseModel):
    score: float
    grade: str
    subscores: list[SubScore]
    explanation: Explanation


WEIGHTS = {
    "liquidity": 0.20, "cashflow": 0.25, "spending_control": 0.15, "income_stability": 0.15,
    "resilience": 0.15, "goal_progress": 0.10,
}
LABELS = {
    "liquidity": "Liquidité", "cashflow": "Cashflow", "spending_control": "Maîtrise des dépenses",
    "income_stability": "Stabilité des revenus", "resilience": "Résilience", "goal_progress": "Objectifs",
}


def compute_state_score(inp: StateInputs) -> StateScore:
    raw: dict[str, tuple[float, str, str]] = {}
    if inp.essential_monthly > 0:
        months = float(inp.liquid_assets / inp.essential_monthly)
        raw["liquidity"] = (piecewise(months, [(0, 0), (1, 25), (3, 65), (6, 100)]), f"{months:.1f} mois",
                            "mois de dépenses essentielles couverts par les liquidités (cible 6)")
    if inp.savings_rate_3m is not None:
        sr = inp.savings_rate_3m
        raw["cashflow"] = (piecewise(sr, [(-0.1, 0), (0, 40), (0.1, 65), (0.2, 85), (0.3, 100)]),
                           f"{sr * 100:.0f} %", "taux d'épargne moyen sur 3 mois")
    if inp.spend_ratio is not None:
        r = inp.spend_ratio
        raw["spending_control"] = (piecewise(r, [(0.9, 100), (1.0, 80), (1.2, 45), (1.5, 0)]),
                                   f"{(r - 1) * 100:+.0f} %",
                                   "dépenses courantes 30 j vs moyenne des 3 mois précédents (hors récurrents)")
    if inp.income_cv is not None:
        cv = inp.income_cv
        raw["income_stability"] = (piecewise(cv, [(0, 100), (0.1, 85), (0.3, 50), (0.6, 10)]),
                                   f"CV {cv:.2f}", "variabilité des revenus mensuels (6 mois)")
    if inp.total_monthly_expenses > 0:
        runway = float(inp.liquid_assets / inp.total_monthly_expenses)
        raw["resilience"] = (piecewise(runway, [(0, 0), (1, 20), (3, 60), (6, 100)]), f"{runway:.1f} mois",
                             "mois de train de vie complet sans revenu")
    if inp.goal_progress is not None:
        raw["goal_progress"] = (inp.goal_progress * 100, f"{inp.goal_progress * 100:.0f} %",
                                "avancement moyen des objectifs actifs")

    total_weight = sum(WEIGHTS[k] for k in raw) or 1.0
    subs: list[SubScore] = []
    for k, (score, metric, detail) in raw.items():
        w = WEIGHTS[k] / total_weight
        subs.append(SubScore(key=k, label=LABELS[k], score=round(score, 1), weight=round(w, 4),
                             points=round(score * w, 2), metric=metric, detail=detail))
    score = round(sum(s.points for s in subs), 1)
    grade = "excellent" if score >= 80 else "solide" if score >= 65 else "fragile" if score >= 45 else "tendu"
    return StateScore(
        score=score, grade=grade, subscores=subs,
        explanation=Explanation(
            method="Moyenne pondérée de sous-scores calculés par interpolation linéaire sur des seuils fixes ; "
                   "les sous-scores sans données sont exclus et les poids renormalisés.",
            lines=[ExplainLine(label=f"{s.label} ({s.metric})", amount=None, op="+",
                               detail=f"{s.score:.0f}/100 × {s.weight:.0%} = {s.points:.1f} pts")
                   for s in subs],
            confidence=inp.data_confidence,
        ),
    )


class ScoreChange(BaseModel):
    key: str
    label: str
    delta_points: float
    text: str


def diff_scores(previous: list[SubScore] | list[dict[str, object]], current: list[SubScore]) -> list[ScoreChange]:
    prev = {}
    for s in previous:
        d = s.model_dump() if isinstance(s, SubScore) else s
        prev[str(d["key"])] = float(d["points"])  # type: ignore[arg-type]
    out = []
    for s in current:
        delta = round(s.points - prev.get(s.key, s.points), 1)
        if abs(delta) >= 0.5:
            verb = "amélioré(e)" if delta > 0 else "dégradé(e)"
            out.append(ScoreChange(key=s.key, label=s.label, delta_points=delta,
                                   text=f"{delta:+.0f} points : {s.label.lower()} {verb} ({s.metric})"))
    out.sort(key=lambda c: -abs(c.delta_points))
    return out
