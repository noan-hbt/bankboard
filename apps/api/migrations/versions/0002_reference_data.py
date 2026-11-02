"""Seed system categories, merchants, aliases and classification rules.

Revision ID: 0002_reference_data
Revises: 0001_initial
Create Date: 2026-11-02
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.orm import Session

from bankboard.pipeline.reference_data import ensure_reference_data

revision = "0002_reference_data"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    session = Session(bind=op.get_bind())
    ensure_reference_data(session)
    session.flush()


def downgrade() -> None:
    op.execute("DELETE FROM classification_rules WHERE user_id IS NULL")
    op.execute("DELETE FROM merchant_aliases WHERE user_id IS NULL")
    op.execute("DELETE FROM merchants WHERE user_id IS NULL AND source = 'seed'")
    op.execute("DELETE FROM categories WHERE user_id IS NULL")
