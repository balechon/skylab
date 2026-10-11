"""Tiempo real en cada zona de FC en lugar de una sola zona por sesión.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sesion_realizada",
        sa.Column("segundos_por_zona", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.drop_column("sesion_realizada", "fc_zona")


def downgrade() -> None:
    op.add_column("sesion_realizada", sa.Column("fc_zona", sa.String(2), nullable=True))
    op.drop_column("sesion_realizada", "segundos_por_zona")
