# Contratos del agente: lo que entra (la solicitud y el contexto ya cargado)
# y lo que sale (el resultado que entrega con la tool entregar_resultado,
# antes de pasar por la guardia final).
#
# El contexto se carga antes del grafo. Durante el grafo el agente no toca
# la base de datos: trabaja sobre este contexto en memoria, y solo si la
# guardia aprueba el resultado se persiste (ver servicio.py).

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from core.deviation import EvaluacionSemana
from core.methodology import PerfilMetodologia
from core.training import Carrera, ModoPlan, Plan, SesionRealizada
from core.validator import Violacion


class Operacion(str, Enum):
    CREAR_CICLO = "crear_ciclo"
    AJUSTE_SEMANAL = "ajuste_semanal"


# ---------- entrada ----------

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


# ---------- salida ----------

class EstadoResultado(str, Enum):
    PLAN_VALIDO = "plan_valido"
    SIN_SOLUCION = "sin_solucion"


class Justificacion(BaseModel):
    decision: str
    regla_ids: list[str] = Field(min_length=1)


class ResultadoAgente(BaseModel):
    estado: EstadoResultado
    plan: Optional[Plan] = None
    justificaciones: list[Justificacion] = Field(default_factory=list)
    violaciones: list[Violacion] = Field(default_factory=list)
    resumen: str  # texto corto para la notificación

    @model_validator(mode="after")
    def validar_coherencia(self) -> "ResultadoAgente":
        if self.estado == EstadoResultado.PLAN_VALIDO:
            if self.plan is None:
                raise ValueError("Un resultado plan_valido necesita el plan")
            if not self.justificaciones:
                raise ValueError("Un resultado plan_valido necesita justificaciones con sus regla_ids")
        elif not self.violaciones:
            raise ValueError("Un resultado sin_solucion necesita las violaciones que lo impiden")
        return self
