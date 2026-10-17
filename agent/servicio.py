# Orquesta una ejecución completa del agente:
#   1. carga el contexto (Postgres + perfil YAML) y, en el ajuste semanal,
#      evalúa la semana cerrada con el motor;
#   2. corre el agente sobre ese contexto en memoria;
#   3. guarda la versión nueva del plan (si la guardia la aceptó) y el
#      registro de la ejecución en una sola transacción.

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from agent.agente import EjecucionAgente, ejecutar_agente
from agent.contexto import ContextoAgente, SolicitudCiclo
from agent.resultado import EstadoResultado, Operacion
from core.training import Microciclo, Plan
from core.deviation import EvaluacionSemana, evaluar_semana
from core.loader import cargar_perfil
from persistence import repository as repo

def perfiles_dir() -> Path:
    """Carpeta de perfiles YAML: PB_COACH_PERFILES_DIR, o methodology/profiles
    relativa al directorio de trabajo (la raíz del repo, o /app en Docker)."""
    return Path(os.environ.get("PB_COACH_PERFILES_DIR", "methodology/profiles"))
SEMANAS_DE_HISTORIAL = 16


class SinPlanVigente(RuntimeError):
    pass


class PerfilIncompleto(RuntimeError):
    """El perfil no tiene lo necesario para planificar sin inventar."""


def _exigir_secuencia(perfil, nombre_perfil: str, modo) -> None:
    # Se comprueba antes de llamar al modelo: sin secuencia de bloques no hay
    # plan posible sin inventar, y no tiene sentido gastar tokens.
    if perfil.secuencia_para(modo) is None:
        raise PerfilIncompleto(
            f"El perfil {nombre_perfil} no define secuencias_bloques para el modo {modo.value}: "
            "añádela al YAML antes de planificar."
        )


class RespuestaServicio(BaseModel):
    ejecucion: EjecucionAgente
    plan_id: Optional[int] = None
    version: Optional[int] = None
    evaluacion: Optional[EvaluacionSemana] = None


def _sesiones_recientes(sesiones_db: sessionmaker, hoy: date):
    with sesiones_db() as db:
        return repo.sesiones_entre(db, hoy - timedelta(weeks=SEMANAS_DE_HISTORIAL + 1), hoy)


def _ultimo_microciclo_cerrado(plan: Plan, hoy: date) -> Optional[Microciclo]:
    cerrados = [m for meso in plan.mesociclos for m in meso.microciclos if m.fecha_fin < hoy]
    return cerrados[-1] if cerrados else None


def _registro(ejecucion: EjecucionAgente) -> dict[str, Any]:
    if ejecucion.resultado is not None:
        return ejecucion.resultado.model_dump(mode="json")
    return {"detalle": ejecucion.detalle}


def crear_ciclo(
    sesiones_db: sessionmaker, cliente: Any, solicitud: SolicitudCiclo, hoy: Optional[date] = None
) -> RespuestaServicio:
    hoy = hoy or date.today()
    perfil = cargar_perfil(perfiles_dir() / f"{solicitud.perfil}.yaml")
    _exigir_secuencia(perfil, solicitud.perfil, solicitud.modo)
    ctx = ContextoAgente(
        operacion=Operacion.CREAR_CICLO,
        hoy=hoy,
        nombre_perfil=solicitud.perfil,
        perfil=perfil,
        sesiones=_sesiones_recientes(sesiones_db, hoy),
        solicitud=solicitud,
    )
    ejecucion = ejecutar_agente(ctx, cliente)
    respuesta = RespuestaServicio(ejecucion=ejecucion)

    with sesiones_db.begin() as db:
        version_id = None
        resultado = ejecucion.resultado
        if resultado is not None and resultado.estado == EstadoResultado.PLAN_VALIDO:
            respuesta.plan_id = repo.crear_plan(db, resultado.plan, perfil=solicitud.perfil)
            respuesta.version = 1
            version_id = repo.id_version(db, respuesta.plan_id, 1)
        repo.registrar_ejecucion(
            db,
            operacion=Operacion.CREAR_CICLO.value,
            estado=resultado.estado.value if resultado else ejecucion.estado,
            resultado=_registro(ejecucion),
            plan_version_id=version_id,
            modelo=ejecucion.modelo,
            tokens_entrada=ejecucion.tokens_entrada,
            tokens_salida=ejecucion.tokens_salida,
        )
    return respuesta


def ajuste_semanal(sesiones_db: sessionmaker, cliente: Any, hoy: Optional[date] = None) -> RespuestaServicio:
    hoy = hoy or date.today()
    with sesiones_db() as db:
        vigente = repo.plan_vigente(db)
        if vigente is None:
            raise SinPlanVigente("No hay un plan activo que ajustar: primero hay que crear un ciclo.")
        plan_id, plan = vigente
        nombre_perfil = repo.perfil_del_plan(db, plan_id)

    perfil = cargar_perfil(perfiles_dir() / f"{nombre_perfil}.yaml")
    _exigir_secuencia(perfil, nombre_perfil, plan.modo)
    sesiones = _sesiones_recientes(sesiones_db, hoy)
    cerrado = _ultimo_microciclo_cerrado(plan, hoy)
    evaluacion = evaluar_semana(cerrado, sesiones, perfil) if cerrado else None

    ctx = ContextoAgente(
        operacion=Operacion.AJUSTE_SEMANAL,
        hoy=hoy,
        nombre_perfil=nombre_perfil,
        perfil=perfil,
        sesiones=sesiones,
        plan_vigente=plan,
        evaluacion=evaluacion,
    )
    ejecucion = ejecutar_agente(ctx, cliente)
    respuesta = RespuestaServicio(ejecucion=ejecucion, plan_id=plan_id, evaluacion=evaluacion)

    with sesiones_db.begin() as db:
        version_id = None
        resultado = ejecucion.resultado
        if resultado is not None and resultado.estado == EstadoResultado.PLAN_VALIDO:
            accion = evaluacion.accion if evaluacion else None
            motivo = f"{accion.regla_id}: {accion.accion.value}" if accion else "ajuste_semanal: sin acción, se sigue el plan"
            version_id = repo.guardar_version(db, plan_id, resultado.plan, motivo=motivo)
            respuesta.version = resultado.plan.version
        repo.registrar_ejecucion(
            db,
            operacion=Operacion.AJUSTE_SEMANAL.value,
            estado=resultado.estado.value if resultado else ejecucion.estado,
            resultado=_registro(ejecucion),
            plan_version_id=version_id,
            modelo=ejecucion.modelo,
            tokens_entrada=ejecucion.tokens_entrada,
            tokens_salida=ejecucion.tokens_salida,
        )
    return respuesta
