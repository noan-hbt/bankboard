"""Built-in P0 modules."""

from __future__ import annotations

from sqlalchemy.orm import Session

from bankboard.detectors import core as det
from bankboard.models import DomainEvent
from bankboard.modules.registry import Module, WidgetSpec, register_module


def _on_sync_completed(session: Session, event: DomainEvent) -> None:
    from datetime import date

    from bankboard.services.analysis import refresh_user

    if event.user_id is not None:
        as_of = event.payload.get("as_of")
        refresh_user(session, event.user_id, today=date.fromisoformat(as_of) if as_of else None)


register_module(Module(
    key="banking", title="Banque", tier="P0", description="Connexions, synchronisation, qualité des données.",
    widgets=[WidgetSpec("data_health", "Data Health", "list", "/api/data-health", w=4, h=4)],
    detectors=[det.connection_health, det.duplicate_charge],
    event_handlers={"bank.sync.completed": [_on_sync_completed]},
))
register_module(Module(
    key="financial_state", title="Financial State", tier="P0", description="Score global explicable.",
    widgets=[
        WidgetSpec("financial_state", "Financial State", "score", "/api/state", w=4, h=4),
        WidgetSpec("wealth_trajectory", "Trajectoire patrimoine", "series", "/api/snapshots?days=365", w=8, h=5,
                   min_w=4),
    ],
))
register_module(Module(
    key="safe_to_spend", title="Safe to spend", tier="P0", description="Ce que tu peux dépenser sans risque.",
    widgets=[WidgetSpec("safe_to_spend", "Safe to spend", "metric", "/api/safe-to-spend", w=4, h=4)],
    detectors=[det.dormant_cash],
))
register_module(Module(
    key="cashflow", title="Cashflow", tier="P0", description="Revenus, dépenses, épargne.",
    widgets=[
        WidgetSpec("cashflow_monthly", "Cashflow mensuel", "series", "/api/metrics/cashflow/monthly", w=8, h=5),
        WidgetSpec("spending_breakdown", "Dépenses par catégorie", "breakdown", "/api/metrics/cashflow?days=30",
                   w=4, h=5),
    ],
))
register_module(Module(
    key="spending", title="Dépenses", tier="P0", description="Détection de hausses et d'anomalies.",
    detectors=[det.category_spike, det.unusual_amount],
))
register_module(Module(
    key="forecasting", title="Prévisions", tier="P0", description="Timeline attendue et liquidité future.",
    widgets=[
        WidgetSpec("next_30_days", "30 prochains jours", "timeline", "/api/timeline?days=30", w=6, h=5),
        WidgetSpec("liquidity", "Liquidité future", "series", "/api/timeline?days=45", w=6, h=4),
    ],
    detectors=[det.upcoming_large_outflow],
))
register_module(Module(
    key="subscriptions", title="Abonnements", tier="P0", description="Récurrences et abonnements.",
    widgets=[WidgetSpec("subscriptions", "Abonnements & récurrents", "list", "/api/recurring", w=4, h=5)],
    detectors=[det.new_recurring],
))
register_module(Module(
    key="what_changed", title="What Changed", tier="P0", description="Ce qui a changé et pourquoi.",
    widgets=[WidgetSpec("what_changed", "Ce qui a changé", "breakdown", "/api/what-changed?preset=30d", w=6, h=5)],
))
register_module(Module(
    key="alerts", title="Attention & opportunités", tier="P0", description="Insights priorisés.",
    widgets=[
        WidgetSpec("attention", "Attention", "insights", "/api/insights?section=attention", w=6, h=4),
        WidgetSpec("opportunities", "Opportunités", "insights", "/api/insights?section=opportunity", w=6, h=3),
        WidgetSpec("feed", "Feed", "feed", "/api/feed", w=4, h=6),
    ],
))
register_module(Module(
    key="advisor", title="Ask your money", tier="P0", description="Questions en langage naturel.",
    widgets=[WidgetSpec("ask", "Ask your money", "ask", "/api/ask", w=8, h=4)],
))
