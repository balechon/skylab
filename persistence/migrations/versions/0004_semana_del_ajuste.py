"""Semana evaluada en cada ajuste semanal (para no ajustarla dos veces).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ejecucion_agente", sa.Column("semana", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("ejecucion_agente", "semana")
