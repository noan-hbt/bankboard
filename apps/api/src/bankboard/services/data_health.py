"""Data Health: what could make the numbers wrong, and a Data Confidence Score."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

import polars as pl
from pydantic import BaseModel

from bankboard.core.clock import utcnow
from bankboard.core.money import from_cents

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from bankboard.services.context import FinancialContext


class HealthIssue(BaseModel):
    key: str
    severity: Literal["info", "warning", "critical"]
    title: str
    count: int = 0
    amount: Decimal | None = None
    penalty: float = 0.0
    action: str | None = None


class DataHealth(BaseModel):
    confidence: float
    issues: list[HealthIssue]
    transactions: int
    categorized_share: float


def compute_data_health(session: Session, ctx: FinancialContext) -> DataHealth:
    issues: list[HealthIssue] = []
    df = ctx.df.filter(pl.col("booking_date") >= ctx.today - timedelta(days=90))
    spend = df.filter(pl.col("kind").is_in(["consumption", "fee", "debt_payment"]))
    total = int(spend["amount"].abs().sum() or 0) if not spend.is_empty() else 0

    uncategorized = spend.filter(pl.col("category_key") == "uncategorized")
    unc_amount = int(uncategorized["amount"].abs().sum() or 0) if not uncategorized.is_empty() else 0
    unc_share = unc_amount / total if total else 0.0
    if uncategorized.height:
        issues.append(HealthIssue(key="uncategorized", severity="warning" if unc_share > 0.05 else "info",
                                  title="Transactions non classées (90 j)", count=uncategorized.height,
                                  amount=from_cents(unc_amount), penalty=round(min(0.3, unc_share), 3),
                                  action="Classer ces transactions améliore toutes les analyses."))
    low = df.filter(pl.col("category_confidence") < 0.6)
    if low.height:
        issues.append(HealthIssue(key="low_confidence", severity="info", title="Catégories incertaines",
                                  count=low.height, penalty=round(min(0.1, low.height / max(df.height, 1)), 3)))
    if not df.is_empty():
        dupes = (df.filter(pl.col("kind") == "consumption")
                 .group_by(["account_id", "booking_date", "amount", "merchant_id"]).agg(pl.len().alias("n"))
                 .filter(pl.col("n") > 1))
        if dupes.height:
            issues.append(HealthIssue(key="possible_duplicates", severity="warning", title="Doublons possibles",
                                      count=int(dupes.height), action="Vérifie s'il s'agit de doubles débits."))
    now = utcnow()
    for c in ctx.connections:
        if c.status in {"reauth_required", "error"}:
            issues.append(HealthIssue(key=f"connection:{c.id}", severity="critical",
                                      title=f"{c.institution_name} : reconnexion nécessaire", penalty=0.3,
                                      action="Relancer l'autorisation bancaire."))
        elif c.consent_valid_until and c.consent_valid_until - now < timedelta(days=14):
            days = max(0, (c.consent_valid_until - now).days)
            issues.append(HealthIssue(key=f"consent:{c.id}", severity="warning",
                                      title=f"Consentement {c.institution_name} expire dans {days} j",
                                      penalty=0.05, action="Renouveler le consentement."))
        if c.status == "active" and (c.last_synced_at is None or now - c.last_synced_at > timedelta(days=2)):
            issues.append(HealthIssue(key=f"stale:{c.id}", severity="warning",
                                      title=f"{c.institution_name} non synchronisé depuis plus de 48 h",
                                      penalty=0.15))
    foreign = [a for a in ctx.accounts if a.is_active and a.currency != ctx.user.base_currency]
    if foreign:
        issues.append(HealthIssue(key="foreign_currency", severity="info",
                                  title="Comptes en devise étrangère exclus des agrégats", count=len(foreign)))
    if not ctx.accounts:
        issues.append(HealthIssue(key="no_accounts", severity="critical", title="Aucun compte connecté",
                                  penalty=1.0, action="Connecter une banque ou activer le mode démo."))
    confidence = max(0.0, round(1.0 - sum(i.penalty for i in issues), 3))
    return DataHealth(confidence=confidence, issues=issues, transactions=ctx.df.height,
                      categorized_share=round(1 - unc_share, 4))
