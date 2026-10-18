"""Límites de zona con los que se registró el tiempo por zona de cada sesión.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sesion_realizada",
        sa.Column("limites_zonas", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("sesion_realizada", "limites_zonas")
