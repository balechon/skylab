"""Registro de entrenamientos publicados en Garmin.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publicacion_garmin",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plan.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("garmin_workout_id", sa.BigInteger(), nullable=False),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("retirado_en", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_publicacion_garmin_fecha", "publicacion_garmin", ["fecha"])


def downgrade() -> None:
    op.drop_index("ix_publicacion_garmin_fecha", table_name="publicacion_garmin")
    op.drop_table("publicacion_garmin")
