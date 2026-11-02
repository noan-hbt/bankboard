"""Initial schema (P0).

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-02
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parent.parent / "sql" / "0001_initial.sql"

TABLES = [
    "audit_logs", "dashboard_layouts", "advisor_messages", "advisor_conversations", "feed_items",
    "recommendations", "insights", "domain_events", "financial_snapshots", "goal_contributions", "goals",
    "expected_transactions", "recurring_patterns", "transaction_tags", "tags", "transactions",
    "classification_rules", "merchant_aliases", "merchants", "categories", "transaction_raw", "sync_jobs",
    "balances", "accounts", "bank_sessions", "bank_connections", "bank_auth_requests",
    "user_preferences", "user_sessions", "users",
]


def upgrade() -> None:
    op.execute(SQL.read_text())


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
