# Todo lo que el agente necesita, cargado antes del bucle. Durante el bucle
# el agente no toca la base de datos: trabaja sobre este contexto en memoria,
# y solo si la guardia aprueba el resultado se persiste (ver servicio.py).

from datetime import date
from typing import Optional

from pydantic import BaseModel, model_validator

from agent.resultado import Operacion
from core.methodology import PerfilMetodologia
from core.training import Carrera, ModoPlan, Plan, SesionRealizada
from core.deviation import EvaluacionSemana


class SolicitudCiclo(BaseModel):
    """Lo que se pide al crear un ciclo nuevo."""

    modo: ModoPlan
    perfil: str
    fecha_objetivo: date
    carrera: Optional[Carrera] = None


class ContextoAgente(BaseModel):
    operacion: Operacion
    hoy: date
    nombre_perfil: str
    perfil: PerfilMetodologia
    sesiones: list[SesionRealizada]
    solicitud: Optional[SolicitudCiclo] = None  # solo crear_ciclo
    plan_vigente: Optional[Plan] = None          # solo ajuste_semanal
    evaluacion: Optional[EvaluacionSemana] = None  # solo ajuste_semanal, ya calculada por el motor

    @model_validator(mode="after")
    def validar_operacion(self) -> "ContextoAgente":
        if self.operacion == Operacion.CREAR_CICLO and self.solicitud is None:
            raise ValueError("crear_ciclo necesita la solicitud del ciclo")
        if self.operacion == Operacion.AJUSTE_SEMANAL and self.plan_vigente is None:
            raise ValueError("ajuste_semanal necesita un plan vigente")
        return self


def ids_del_perfil(perfil: PerfilMetodologia) -> set[str]:
    return {
        r.id
        for lista in (
            perfil.reglas,
            perfil.restricciones_globales,
            perfil.reglas_secuenciales,
            perfil.reglas_conteo_microciclo,
            perfil.reglas_ajuste,
        )
        for r in lista
    }
