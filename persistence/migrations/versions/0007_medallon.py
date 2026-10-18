"""Pipeline medallón: bronze (Garmin crudo), silver y gold (vistas) y coste
y duración de cada ejecución del agente.

bronze_*  tablas con los datos tal como llegan
silver_*  vistas: datos limpios y con forma de tabla
gold_*    vistas: agregados listos para consumir (monitor, Notion)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-18
"""

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Precio por millón de tokens (USD). Escritura de caché = 1,25 × entrada
# (TTL de 5 minutos); lectura = la tarifa publicada de cada modelo.
PRECIOS = [
    ("anthropic:claude-opus-5-5", 4.00, 20.00, 0.20, 5.00),
    ("anthropic:claude-sonnet-5-5", 2.00, 10.00, 0.20, 2.50),
    ("anthropic:claude-haiku-5-5", 0.10, 0.50, 0.01, 0.125),
]

VISTAS = {
    "silver_sesion": """
        SELECT s.id, s.garmin_activity_id, s.fecha,
               s.fecha - (extract(isodow FROM s.fecha)::int - 1) AS semana,
               round(extract(epoch FROM s.duracion)::numeric / 60, 1) AS duracion_min,
               s.distancia_km, s.desnivel_positivo_m, s.fc_media, s.carga_epoc, s.rpe, s.sensaciones,
               CASE WHEN s.rpe IS NOT NULL
                    THEN round(s.rpe * extract(epoch FROM s.duracion)::numeric / 60, 1) END AS carga_srpe,
               round(coalesce((s.segundos_por_zona->>'Z1')::numeric, 0) / 60, 1) AS min_z1,
               round(coalesce((s.segundos_por_zona->>'Z2')::numeric, 0) / 60, 1) AS min_z2,
               round(coalesce((s.segundos_por_zona->>'Z3')::numeric, 0) / 60, 1) AS min_z3,
               round(coalesce((s.segundos_por_zona->>'Z4')::numeric, 0) / 60, 1) AS min_z4,
               round(coalesce((s.segundos_por_zona->>'Z5')::numeric, 0) / 60, 1) AS min_z5,
               s.limites_zonas
        FROM sesion_realizada s
    """,
    "silver_ejecucion": """
        SELECT e.id, e.creado_en, e.creado_en::date AS fecha, e.operacion, e.estado, e.semana, e.modelo,
               e.plan_version_id IS NOT NULL AS aceptada,
               coalesce(e.tokens_entrada, 0) AS tokens_entrada,
               coalesce(e.tokens_salida, 0) AS tokens_salida,
               coalesce(e.tokens_cache_lectura, 0) AS tokens_cache_lectura,
               coalesce(e.tokens_cache_escritura, 0) AS tokens_cache_escritura,
               e.duracion_segundos,
               round(((greatest(coalesce(e.tokens_entrada, 0) - coalesce(e.tokens_cache_lectura, 0)
                                - coalesce(e.tokens_cache_escritura, 0), 0) * p.entrada
                       + coalesce(e.tokens_cache_lectura, 0) * p.cache_lectura
                       + coalesce(e.tokens_cache_escritura, 0) * p.cache_escritura
                       + coalesce(e.tokens_salida, 0) * p.salida) / 1000000)::numeric, 4) AS coste_usd,
               CASE WHEN e.duracion_segundos > 0
                    THEN round((coalesce(e.tokens_salida, 0) / e.duracion_segundos)::numeric, 1) END
                    AS tokens_salida_por_segundo
        FROM ejecucion_agente e
        LEFT JOIN precio_modelo p ON p.modelo = e.modelo
    """,
    # Semanas del plan vigente (la última versión del último plan activo).
    "silver_plan_semana": """
        WITH vigente AS (
            SELECT p.id AS plan_id, v.version, v.contenido
            FROM plan p
            JOIN plan_version v ON v.plan_id = p.id
            WHERE p.id = (SELECT max(id) FROM plan WHERE activo)
            ORDER BY v.version DESC
            LIMIT 1
        )
        SELECT g.plan_id, g.version,
               meso->>'objetivo' AS bloque,
               (micro->>'fecha_inicio')::date AS semana,
               micro->>'tipo_microciclo' AS tipo,
               round(extract(epoch FROM (micro->'objetivos'->>'duracion')::interval)::numeric / 3600, 2)
                   AS horas_objetivo,
               (micro->'objetivos'->>'volumen_km')::numeric AS km_objetivo,
               (micro->'objetivos'->>'desnivel_positivo_m')::numeric AS dmas_objetivo,
               jsonb_array_length(micro->'sesiones') > 0 AS detallada
        FROM vigente g,
             jsonb_array_elements(g.contenido->'mesociclos') AS meso,
             jsonb_array_elements(meso->'microciclos') AS micro
    """,
    "gold_carga_semanal": """
        SELECT semana, count(*) AS sesiones,
               round(sum(duracion_min) / 60, 2) AS horas,
               round(sum(distancia_km)::numeric, 1) AS km,
               round(sum(coalesce(desnivel_positivo_m, 0))::numeric) AS dmas,
               round(sum(carga_epoc)::numeric, 1) AS carga_epoc,
               round(sum(carga_srpe), 1) AS carga_srpe,
               round(avg(rpe)::numeric, 1) AS rpe_medio,
               round(avg(fc_media)::numeric) AS fc_media
        FROM silver_sesion
        GROUP BY semana
    """,
    "gold_adherencia_semanal": """
        SELECT p.semana, p.bloque, p.tipo, p.detallada,
               p.horas_objetivo, coalesce(c.horas, 0) AS horas_hechas,
               CASE WHEN p.horas_objetivo > 0 THEN round(100 * coalesce(c.horas, 0) / p.horas_objetivo, 1) END
                   AS adherencia_horas_pct,
               p.km_objetivo, coalesce(c.km, 0) AS km_hechos,
               p.dmas_objetivo, coalesce(c.dmas, 0) AS dmas_hecho,
               coalesce(c.sesiones, 0) AS sesiones, c.carga_epoc, c.rpe_medio, c.fc_media
        FROM silver_plan_semana p
        LEFT JOIN gold_carga_semanal c ON c.semana = p.semana
    """,
    "gold_agente_resumen": """
        SELECT count(*) AS ejecuciones,
               count(*) FILTER (WHERE aceptada) AS aceptadas,
               coalesce(sum(coste_usd), 0) AS coste_total_usd,
               round(avg(coste_usd), 4) AS coste_medio_usd,
               coalesce(sum(tokens_entrada), 0) AS tokens_entrada,
               coalesce(sum(tokens_salida), 0) AS tokens_salida,
               coalesce(sum(tokens_cache_lectura), 0) AS tokens_cache_lectura,
               round(avg(duracion_segundos)::numeric, 1) AS duracion_media_segundos,
               round(avg(tokens_salida_por_segundo), 1) AS tokens_salida_por_segundo,
               max(creado_en) AS ultima_ejecucion
        FROM silver_ejecucion
    """,
    "gold_agente_por_mes": """
        SELECT date_trunc('month', creado_en)::date AS mes, operacion,
               count(*) AS ejecuciones, count(*) FILTER (WHERE aceptada) AS aceptadas,
               coalesce(sum(coste_usd), 0) AS coste_usd,
               coalesce(sum(tokens_entrada + tokens_salida), 0) AS tokens
        FROM silver_ejecucion
        GROUP BY 1, 2
    """,
}

# Orden de creación (las vistas gold dependen de las silver).
ORDEN = list(VISTAS)


def upgrade() -> None:
    for columna, tipo in (
        ("tokens_cache_lectura", sa.Integer()),
        ("tokens_cache_escritura", sa.Integer()),
        ("duracion_segundos", sa.Float()),
    ):
        op.add_column("ejecucion_agente", sa.Column(columna, tipo, nullable=True))

    op.create_table(
        "bronze_garmin_actividad",
        sa.Column("garmin_activity_id", sa.BigInteger(), primary_key=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("recibido_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resumen", JSONB(), nullable=False),
        sa.Column("detalle", JSONB(), nullable=False),
        sa.Column("zonas", JSONB(), nullable=False),
    )
    op.create_index("ix_bronze_garmin_actividad_fecha", "bronze_garmin_actividad", ["fecha"])

    precios = op.create_table(
        "precio_modelo",
        sa.Column("modelo", sa.String(80), primary_key=True),
        sa.Column("entrada", sa.Float(), nullable=False),
        sa.Column("salida", sa.Float(), nullable=False),
        sa.Column("cache_lectura", sa.Float(), nullable=False),
        sa.Column("cache_escritura", sa.Float(), nullable=False),
        sa.Column("fuente", sa.Text(), nullable=False),
        sa.Column("actualizado", sa.Date(), nullable=False),
    )
    op.bulk_insert(
        precios,
        [
            {"modelo": m, "entrada": e, "salida": s, "cache_lectura": cl, "cache_escritura": ce,
             "fuente": "Tarifas publicadas de Anthropic (API directa); escritura de caché = 1,25 × entrada",
             "actualizado": date(2026, 10, 18)}
            for m, e, s, cl, ce in PRECIOS
        ],
    )

    for nombre in ORDEN:
        op.execute(f"CREATE VIEW {nombre} AS {VISTAS[nombre]}")


def downgrade() -> None:
    for nombre in reversed(ORDEN):
        op.execute(f"DROP VIEW IF EXISTS {nombre}")
    op.drop_table("precio_modelo")
    op.drop_index("ix_bronze_garmin_actividad_fecha", "bronze_garmin_actividad")
    op.drop_table("bronze_garmin_actividad")
    for columna in ("duracion_segundos", "tokens_cache_escritura", "tokens_cache_lectura"):
        op.drop_column("ejecucion_agente", columna)
