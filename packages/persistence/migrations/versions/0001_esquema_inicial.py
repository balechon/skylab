"""Esquema inicial: plan, plan_version, sesion_realizada, ejecucion_agente.

Revision ID: 0001
Revises:
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("modo", sa.String(20), nullable=False),
        sa.Column("perfil", sa.String(100), nullable=False),
        sa.Column("fecha_inicio", sa.Date(), nullable=False),
        sa.Column("fecha_objetivo", sa.Date(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
    )

    op.create_table(
        "plan_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plan.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("contenido", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("plan_id", "version"),
    )

    op.create_table(
        "sesion_realizada",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("garmin_activity_id", sa.BigInteger(), nullable=True, unique=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("duracion", sa.Interval(), nullable=False),
        sa.Column("distancia_km", sa.Float(), nullable=False),
        sa.Column("terreno", sa.String(40), nullable=True),
        sa.Column("clase_sesion", sa.String(20), nullable=True),
        sa.Column("tipo_sesion", sa.String(20), nullable=True),
        sa.Column("desnivel_positivo_m", sa.Float(), nullable=True),
        sa.Column("desnivel_negativo_m", sa.Float(), nullable=True),
        sa.Column("fc_media", sa.Integer(), nullable=True),
        sa.Column("fc_zona", sa.String(2), nullable=True),
        sa.Column("ritmo_medio_min_km", sa.Float(), nullable=True),
        sa.Column("rpe", sa.Integer(), nullable=True),
        sa.Column("sensaciones", sa.Text(), nullable=True),
        sa.Column("carga_epoc", sa.Float(), nullable=True),
    )
    op.create_index("ix_sesion_realizada_fecha", "sesion_realizada", ["fecha"])

    op.create_table(
        "ejecucion_agente",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("operacion", sa.String(30), nullable=False),
        sa.Column("estado", sa.String(30), nullable=False),
        sa.Column("plan_version_id", sa.Integer(), sa.ForeignKey("plan_version.id"), nullable=True),
        sa.Column("modelo", sa.String(60), nullable=True),
        sa.Column("tokens_entrada", sa.Integer(), nullable=True),
        sa.Column("tokens_salida", sa.Integer(), nullable=True),
        sa.Column("resultado", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ejecucion_agente")
    op.drop_index("ix_sesion_realizada_fecha", table_name="sesion_realizada")
    op.drop_table("sesion_realizada")
    op.drop_table("plan_version")
    op.drop_table("plan")
