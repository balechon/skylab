"""Ficha del atleta: edad, umbrales, categoría y disponibilidad.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ficha_atleta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("contenido", JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ficha_atleta")
