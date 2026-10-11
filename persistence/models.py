# Tablas de pb-coach (SQLAlchemy 2). El esquema lo crea y lo evoluciona
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
    estado: Mapped[str] = mapped_column(String(30))
    plan_version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("plan_version.id"))
    modelo: Mapped[Optional[str]] = mapped_column(String(60))
    tokens_entrada: Mapped[Optional[int]] = mapped_column(Integer)
    tokens_salida: Mapped[Optional[int]] = mapped_column(Integer)
    resultado: Mapped[dict[str, Any]] = mapped_column(JSONB)
