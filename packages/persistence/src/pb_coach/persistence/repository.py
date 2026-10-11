# Lectura y escritura de pb-coach en Postgres, traduciendo entre filas y
# los modelos de domain/.
#
# Ninguna función hace commit: lo decide quien llama, para que una operación
# completa (p. ej. un ajuste semanal: sesiones + versión nueva + registro de
# la ejecución) sea todo o nada.
#
# Los planes se guardan como JSONB y, al leerlos, se validan otra vez con
# Pydantic: un dato inconsistente en la base nunca entra al motor como si
# fuera válido.

from datetime import date
from enum import Enum
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from pb_coach.domain.training import Plan, SesionRealizada
from pb_coach.persistence.models import (
    EjecucionAgenteFila,
    PlanFila,
    PlanVersionFila,
    SesionRealizadaFila,
)

# ---------- sesiones realizadas ----------

_CAMPOS_SESION = list(SesionRealizada.model_fields)


def _sesion_a_fila(sesion: SesionRealizada) -> dict[str, Any]:
    fila = {
        campo: valor.value if isinstance(valor, Enum) else valor
        for campo, valor in sesion.model_dump().items()
    }
    fila["segundos_por_zona"] = {zona.value: s for zona, s in sesion.segundos_por_zona.items()}
    return fila


def _fila_a_sesion(fila: SesionRealizadaFila) -> SesionRealizada:
    return SesionRealizada.model_validate({campo: getattr(fila, campo) for campo in _CAMPOS_SESION})


def guardar_sesiones(db: Session, sesiones: list[SesionRealizada]) -> int:
    """Inserta las sesiones y devuelve cuántas eran nuevas. Las que ya
    existen (mismo garmin_activity_id) se omiten, así el sync se puede
    repetir sin duplicar."""
    if not sesiones:
        return 0
    sentencia = (
        insert(SesionRealizadaFila)
        .values([_sesion_a_fila(s) for s in sesiones])
        .on_conflict_do_nothing(index_elements=["garmin_activity_id"])
        .returning(SesionRealizadaFila.id)
    )
    return len(db.execute(sentencia).all())


def sesiones_entre(db: Session, desde: date, hasta: date) -> list[SesionRealizada]:
    """Sesiones con fecha en [desde, hasta], en orden cronológico."""
    filas = db.scalars(
        select(SesionRealizadaFila)
        .where(SesionRealizadaFila.fecha.between(desde, hasta))
        .order_by(SesionRealizadaFila.fecha, SesionRealizadaFila.id)
    )
    return [_fila_a_sesion(f) for f in filas]


def ultima_fecha_sincronizada(db: Session) -> Optional[date]:
    """Fecha de la actividad más reciente guardada: el sync trae desde ahí."""
    return db.scalar(select(func.max(SesionRealizadaFila.fecha)))


# ---------- planes y versiones ----------

def crear_plan(db: Session, plan: Plan, perfil: str, motivo: str = "crear_ciclo") -> int:
    """Crea un ciclo nuevo con su versión 1 y lo deja como el único activo.
    Devuelve el id del plan."""
    if plan.version != 1:
        raise ValueError(f"Un plan nuevo empieza en la versión 1, no en la {plan.version}")

    db.execute(update(PlanFila).where(PlanFila.activo).values(activo=False))
    fila = PlanFila(
        modo=plan.modo.value,
        perfil=perfil,
        fecha_inicio=plan.fecha_inicio,
        fecha_objetivo=plan.fecha_objetivo,
        activo=True,
    )
    db.add(fila)
    db.flush()
    db.add(PlanVersionFila(plan_id=fila.id, version=1, motivo=motivo, contenido=plan.model_dump(mode="json")))
    db.flush()
    return fila.id


def guardar_version(db: Session, plan_id: int, plan: Plan, motivo: str) -> int:
    """Añade la siguiente versión de un plan. La versión del objeto debe ser
    exactamente la última + 1: nunca se sobrescribe una versión anterior.
    Devuelve el id de la fila de la versión."""
    ultima = db.scalar(select(func.max(PlanVersionFila.version)).where(PlanVersionFila.plan_id == plan_id))
    if ultima is None:
        raise ValueError(f"No existe el plan {plan_id}")
    if plan.version != ultima + 1:
        raise ValueError(f"Se esperaba la versión {ultima + 1} del plan {plan_id}, llegó la {plan.version}")

    fila = PlanVersionFila(plan_id=plan_id, version=plan.version, motivo=motivo, contenido=plan.model_dump(mode="json"))
    db.add(fila)
    db.flush()
    return fila.id


def plan_vigente(db: Session) -> Optional[tuple[int, Plan]]:
    """La última versión del plan activo, o None si no hay ninguno."""
    fila = db.scalars(
        select(PlanVersionFila)
        .join(PlanFila)
        .where(PlanFila.activo)
        .order_by(PlanVersionFila.version.desc())
        .limit(1)
    ).first()
    if fila is None:
        return None
    return fila.plan_id, Plan.model_validate(fila.contenido)


def historial_versiones(db: Session, plan_id: int) -> list[tuple[int, str, Plan]]:
    """(versión, motivo, plan) de todas las versiones, de la primera a la última."""
    filas = db.scalars(
        select(PlanVersionFila).where(PlanVersionFila.plan_id == plan_id).order_by(PlanVersionFila.version)
    )
    return [(f.version, f.motivo, Plan.model_validate(f.contenido)) for f in filas]


# ---------- ejecuciones del agente ----------

def registrar_ejecucion(
    db: Session,
    operacion: str,
    estado: str,
    resultado: dict[str, Any],
    plan_version_id: Optional[int] = None,
    modelo: Optional[str] = None,
    tokens_entrada: Optional[int] = None,
    tokens_salida: Optional[int] = None,
) -> int:
    fila = EjecucionAgenteFila(
        operacion=operacion,
        estado=estado,
        resultado=resultado,
        plan_version_id=plan_version_id,
        modelo=modelo,
        tokens_entrada=tokens_entrada,
        tokens_salida=tokens_salida,
    )
    db.add(fila)
    db.flush()
    return fila.id


def perfil_del_plan(db: Session, plan_id: int) -> str:
    """Nombre del perfil de metodología con el que se creó el plan."""
    perfil = db.scalar(select(PlanFila.perfil).where(PlanFila.id == plan_id))
    if perfil is None:
        raise ValueError(f"No existe el plan {plan_id}")
    return perfil


def id_version(db: Session, plan_id: int, version: int) -> int:
    """Id de la fila de una versión concreta (para enlazar la ejecución)."""
    return db.scalar(
        select(PlanVersionFila.id).where(PlanVersionFila.plan_id == plan_id, PlanVersionFila.version == version)
    )
