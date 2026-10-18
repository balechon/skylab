# Lectura y escritura de skylab en Postgres, traduciendo entre filas y
# los modelos de domain/.
#
# Ninguna función hace commit: lo decide quien llama, para que una operación
# completa (p. ej. un ajuste semanal: sesiones + versión nueva + registro de
# la ejecución) sea todo o nada.
#
# Los planes se guardan como JSONB y, al leerlos, se validan otra vez con
# Pydantic: un dato inconsistente en la base nunca entra al motor como si
# fuera válido.

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.athlete import FichaAtleta
from core.training import Plan, SesionRealizada
from persistence.models import (
    BronzeGarminActividadFila,
    EjecucionAgenteFila,
    FichaAtletaFila,
    PublicacionGarminFila,
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


def completar_limites_zonas(db: Session, sesiones: list[SesionRealizada]) -> int:
    """Rellena limites_zonas en las sesiones ya guardadas que no lo tienen
    (guardadas antes de registrarlo). Devuelve cuántas se completaron."""
    completadas = 0
    for sesion in sesiones:
        if sesion.garmin_activity_id is None or not sesion.limites_zonas:
            continue
        resultado = db.execute(
            update(SesionRealizadaFila)
            .where(
                SesionRealizadaFila.garmin_activity_id == sesion.garmin_activity_id,
                SesionRealizadaFila.limites_zonas == [],
            )
            .values(limites_zonas=sesion.limites_zonas)
        )
        completadas += resultado.rowcount
    return completadas


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
    semana: Optional[date] = None,
    tokens_cache_lectura: Optional[int] = None,
    tokens_cache_escritura: Optional[int] = None,
    duracion_segundos: Optional[float] = None,
) -> int:
    fila = EjecucionAgenteFila(
        tokens_cache_lectura=tokens_cache_lectura,
        tokens_cache_escritura=tokens_cache_escritura,
        duracion_segundos=duracion_segundos,
        operacion=operacion,
        semana=semana,
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


# ---------- publicaciones en Garmin ----------

class Publicacion(BaseModel):
    id: int
    plan_id: int
    version: int
    fecha: date
    garmin_workout_id: int
    nombre: str


def publicaciones_activas(db: Session, desde: date, hasta: date) -> list[Publicacion]:
    """Entrenamientos publicados y no retirados con fecha en [desde, hasta]."""
    filas = db.scalars(
        select(PublicacionGarminFila)
        .where(PublicacionGarminFila.fecha.between(desde, hasta), PublicacionGarminFila.retirado_en.is_(None))
        .order_by(PublicacionGarminFila.fecha, PublicacionGarminFila.id)
    )
    return [Publicacion.model_validate(f, from_attributes=True) for f in filas]


def registrar_publicacion(
    db: Session, plan_id: int, version: int, fecha: date, garmin_workout_id: int, nombre: str
) -> int:
    fila = PublicacionGarminFila(
        plan_id=plan_id, version=version, fecha=fecha, garmin_workout_id=garmin_workout_id, nombre=nombre
    )
    db.add(fila)
    db.flush()
    return fila.id


def marcar_retirada(db: Session, publicacion_id: int) -> None:
    db.execute(
        update(PublicacionGarminFila)
        .where(PublicacionGarminFila.id == publicacion_id)
        .values(retirado_en=datetime.now(timezone.utc))
    )


def ajuste_aceptado(db: Session, plan_id: int, semana: date) -> Optional[int]:
    """Versión del plan producida por un ajuste semanal ya aceptado para esa
    semana cerrada, o None si todavía no se ajustó."""
    return db.scalar(
        select(PlanVersionFila.version)
        .join(EjecucionAgenteFila, EjecucionAgenteFila.plan_version_id == PlanVersionFila.id)
        .where(
            PlanVersionFila.plan_id == plan_id,
            EjecucionAgenteFila.operacion == "ajuste_semanal",
            EjecucionAgenteFila.semana == semana,
        )
        .order_by(PlanVersionFila.version.desc())
        .limit(1)
    )


def ajustes_aceptados(db: Session, plan_id: int, semana: date) -> int:
    """Cuántos ajustes semanales aceptados (con versión nueva del plan) tiene
    esa semana cerrada: el primero y los recálculos."""
    return db.scalar(
        select(func.count())
        .select_from(EjecucionAgenteFila)
        .join(PlanVersionFila, EjecucionAgenteFila.plan_version_id == PlanVersionFila.id)
        .where(
            PlanVersionFila.plan_id == plan_id,
            EjecucionAgenteFila.operacion == "ajuste_semanal",
            EjecucionAgenteFila.semana == semana,
        )
    )


def guardar_ficha(db: Session, ficha: FichaAtleta) -> int:
    """Añade una versión de la ficha del atleta; pasa a ser la vigente."""
    fila = FichaAtletaFila(contenido=ficha.model_dump(mode="json"))
    db.add(fila)
    db.flush()
    return fila.id


def ficha_vigente(db: Session) -> Optional[FichaAtleta]:
    contenido = db.scalar(select(FichaAtletaFila.contenido).order_by(FichaAtletaFila.id.desc()).limit(1))
    return FichaAtleta.model_validate(contenido) if contenido is not None else None



# ---------- pipeline medallón ----------

def guardar_bronze(db: Session, actividades: list[dict[str, Any]]) -> int:
    """Guarda (o reemplaza) las actividades crudas de Garmin en bronze."""
    if not actividades:
        return 0
    sentencia = insert(BronzeGarminActividadFila).values(actividades)
    sentencia = sentencia.on_conflict_do_update(
        index_elements=["garmin_activity_id"],
        set_={
            "resumen": sentencia.excluded.resumen,
            "detalle": sentencia.excluded.detalle,
            "zonas": sentencia.excluded.zonas,
            "recibido_en": func.now(),
        },
    )
    return len(db.execute(sentencia.returning(BronzeGarminActividadFila.garmin_activity_id)).all())


def _filas(db: Session, consulta: str, **parametros: Any) -> list[dict[str, Any]]:
    return [dict(f._mapping) for f in db.execute(text(consulta), parametros)]


def monitor(db: Session, ultimas_ejecuciones: int = 50) -> dict[str, Any]:
    """La capa gold para el monitor: coste y rendimiento del agente, y la
    carga semanal del plan vigente frente a lo hecho."""
    return {
        "resumen": _filas(db, "SELECT * FROM gold_agente_resumen")[0],
        "por_mes": _filas(db, "SELECT * FROM gold_agente_por_mes ORDER BY mes, operacion"),
        "ejecuciones": _filas(
            db,
            "SELECT id, creado_en, operacion, estado, semana, modelo, aceptada, tokens_entrada, tokens_salida, "
            "tokens_cache_lectura, tokens_cache_escritura, duracion_segundos, coste_usd, tokens_salida_por_segundo "
            "FROM silver_ejecucion ORDER BY id DESC LIMIT :n",
            n=ultimas_ejecuciones,
        ),
        "semanas": _filas(db, "SELECT * FROM gold_adherencia_semanal ORDER BY semana"),
    }
