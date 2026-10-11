# Contrato de salida del agente: lo que entrega con la tool
# entregar_resultado, antes de pasar por la guardia final.

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from pb_coach.domain.training import Plan
from pb_coach.engine.validator import Violacion


class Operacion(str, Enum):
    CREAR_CICLO = "crear_ciclo"
    AJUSTE_SEMANAL = "ajuste_semanal"


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
