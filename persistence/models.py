# Tablas de skylab (SQLAlchemy 2). El esquema lo crea y lo evoluciona
# Alembic (migrations/); estos modelos son su reflejo en Python.
#
# Los modelos de dominio (domain/) no conocen la base de datos: la
# conversión entre filas y objetos Pydantic vive en repository.py.

from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Interval,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PlanFila(Base):
    """Un ciclo de entrenamiento (p. ej. construcción 2026). Sus versiones
    viven en plan_version."""

    __tablename__ = "plan"

    id: Mapped[int] = mapped_column(primary_key=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    modo: Mapped[str] = mapped_column(String(20))
    perfil: Mapped[str] = mapped_column(String(100))
    fecha_inicio: Mapped[date] = mapped_column(Date)
    fecha_objetivo: Mapped[date] = mapped_column(Date)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    versiones: Mapped[list["PlanVersionFila"]] = relationship(
        back_populates="plan", order_by="PlanVersionFila.version"
    )


class PlanVersionFila(Base):
    """Una versión completa del plan, tal cual (JSONB). Cada ajuste semanal
    añade una; las anteriores no se modifican."""

    __tablename__ = "plan_version"
    __table_args__ = (UniqueConstraint("plan_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plan.id"))
    version: Mapped[int] = mapped_column(Integer)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    motivo: Mapped[str] = mapped_column(Text)  # ej. "crear_ciclo" o "EJEMPLO-AJUSTE-001: repetir_microciclo"
    contenido: Mapped[dict[str, Any]] = mapped_column(JSONB)

    plan: Mapped[PlanFila] = relationship(back_populates="versiones")


class SesionRealizadaFila(Base):
    """Una actividad realizada. Columnas normales para poder filtrar y
    agregar por fecha; garmin_activity_id único evita duplicar en el sync."""

    __tablename__ = "sesion_realizada"

    id: Mapped[int] = mapped_column(primary_key=True)
    garmin_activity_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    duracion: Mapped[timedelta] = mapped_column(Interval)
    distancia_km: Mapped[float] = mapped_column(Float)
    terreno: Mapped[Optional[str]] = mapped_column(String(40))
    clase_sesion: Mapped[Optional[str]] = mapped_column(String(20))
    tipo_sesion: Mapped[Optional[str]] = mapped_column(String(20))
    desnivel_positivo_m: Mapped[Optional[float]] = mapped_column(Float)
    desnivel_negativo_m: Mapped[Optional[float]] = mapped_column(Float)
    fc_media: Mapped[Optional[int]] = mapped_column(Integer)
    segundos_por_zona: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    limites_zonas: Mapped[list[int]] = mapped_column(JSONB, default=list)
    ritmo_medio_min_km: Mapped[Optional[float]] = mapped_column(Float)
    rpe: Mapped[Optional[int]] = mapped_column(Integer)
    sensaciones: Mapped[Optional[str]] = mapped_column(Text)
    carga_epoc: Mapped[Optional[float]] = mapped_column(Float)


class EjecucionAgenteFila(Base):
    """Registro de cada ejecución del agente: qué se pidió, qué devolvió y
    cuánto costó en tokens."""

    __tablename__ = "ejecucion_agente"

    id: Mapped[int] = mapped_column(primary_key=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    operacion: Mapped[str] = mapped_column(String(30))  # crear_ciclo | ajuste_semanal
    # En el ajuste semanal: lunes de la semana cerrada que se evaluó. Evita
    # ajustar dos veces la misma semana si el ciclo se lanza de nuevo.
    semana: Mapped[Optional[date]] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(30))
    plan_version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plan_version.id"))
    modelo: Mapped[Optional[str]] = mapped_column(String(60))
    tokens_entrada: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_salida: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_cache_lectura: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_cache_escritura: Mapped[Optional[int]] = mapped_column(Integer)
    duracion_segundos: Mapped[Optional[float]] = mapped_column(Float)
    resultado: Mapped[dict[str, Any]] = mapped_column(JSONB)


class PublicacionGarminFila(Base):
    """Un entrenamiento enviado a Garmin para una fecha. Cuando una versión
    nueva del plan cambia la semana, el anterior se retira (se quita del
    calendario y se borra) y se marca retirado_en; nunca se borra la fila."""

    __tablename__ = "publicacion_garmin"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plan.id"))
    version: Mapped[int] = mapped_column(Integer)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    garmin_workout_id: Mapped[int] = mapped_column(BigInteger)
    nombre: Mapped[str] = mapped_column(String(100))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retirado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class FichaAtletaFila(Base):
    """Una versión de la ficha del atleta (JSONB). Cada cambio añade una fila;
    la vigente es la última. Las anteriores quedan como historial."""

    __tablename__ = "ficha_atleta"

    id: Mapped[int] = mapped_column(primary_key=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    contenido: Mapped[dict[str, Any]] = mapped_column(JSONB)



# ---------- pipeline medallón (bronze → silver → gold) ----------
# bronze_*: los datos tal cual llegan; silver_* y gold_* son vistas SQL
# (migración 0007), así que no tienen modelo aquí.


class BronzeGarminActividadFila(Base):
    """Una actividad de Garmin tal como la devolvió garmin-mcp: resumen,
    detalle y tiempo por zona, sin transformar. Permite rehacer la capa
    silver si cambia cómo se interpreta una actividad."""

    __tablename__ = "bronze_garmin_actividad"

    garmin_activity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    recibido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resumen: Mapped[dict[str, Any]] = mapped_column(JSONB)
    detalle: Mapped[dict[str, Any]] = mapped_column(JSONB)
    zonas: Mapped[list[Any]] = mapped_column(JSONB)


class PrecioModeloFila(Base):
    """Precio por millón de tokens de cada modelo, para calcular el coste de
    las ejecuciones. Es un dato, no código: se actualiza sin desplegar."""

    __tablename__ = "precio_modelo"

    modelo: Mapped[str] = mapped_column(String(80), primary_key=True)
    entrada: Mapped[float] = mapped_column(Float)
    salida: Mapped[float] = mapped_column(Float)
    cache_lectura: Mapped[float] = mapped_column(Float)
    cache_escritura: Mapped[float] = mapped_column(Float)
    fuente: Mapped[str] = mapped_column(Text)
    actualizado: Mapped[date] = mapped_column(Date)
