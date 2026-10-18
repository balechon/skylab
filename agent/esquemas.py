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

from core.athlete import FichaAtleta
from core.deviation import EvaluacionSemana
from core.methodology import PerfilMetodologia
from core.training import Carrera, ModoPlan, Plan, SesionRealizada
from core.validator import Violacion


class Operacion(str, Enum):
    CREAR_CICLO = "crear_ciclo"
    AJUSTE_SEMANAL = "ajuste_semanal"


# ---------- entrada ----------

class ComentarioSesion(BaseModel):
    """Lo que el atleta cuenta de una sesión: cómo se sintió, qué pasó."""

    fecha: date
    texto: str = Field(min_length=1, max_length=500)


class ComentariosAtleta(BaseModel):
    """Comentarios del atleta para el ajuste semanal. `general` sirve para lo
    que viene ("viajo de miércoles a viernes", "cambiemos el fondo al
    domingo"); `por_sesion`, para la semana que se cierra."""

    general: Optional[str] = Field(default=None, max_length=1000)
    por_sesion: list[ComentarioSesion] = Field(default_factory=list)


class SolicitudCiclo(BaseModel):
    """Lo que se pide al crear un ciclo nuevo."""

    modo: ModoPlan
    perfil: str
    fecha_objetivo: date
    carrera: Optional[Carrera] = None
    comentario: Optional[str] = Field(default=None, max_length=1000)  # p. ej. "solo puedo 4 días por semana"


class ContextoAgente(BaseModel):
    operacion: Operacion
    hoy: date
    nombre_perfil: str
    perfil: PerfilMetodologia
    sesiones: list[SesionRealizada]
    solicitud: Optional[SolicitudCiclo] = None  # solo crear_ciclo
    plan_vigente: Optional[Plan] = None          # solo ajuste_semanal
    evaluacion: Optional[EvaluacionSemana] = None  # solo ajuste_semanal, ya calculada por el motor
    comentarios: Optional[ComentariosAtleta] = None  # solo ajuste_semanal
    atleta: Optional[FichaAtleta] = None  # ficha vigente; sin ella no hay restricciones de disponibilidad

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


class Consejo(BaseModel):
    texto: str = Field(min_length=1, max_length=200)
    # Si el consejo se apoya en la metodología, la regla que lo respalda; si
    # se apoya en los datos de la semana, ninguna.
    regla_id: Optional[str] = None


class Feedback(BaseModel):
    """Lo que el entrenador le dice al atleta al cerrar la semana."""

    lo_que_paso: str = Field(min_length=1, max_length=500)
    por_que_cambia: str = Field(min_length=1, max_length=500)
    consejos: list[Consejo] = Field(default_factory=list, max_length=3)


class ResultadoAgente(BaseModel):
    estado: EstadoResultado
    plan: Optional[Plan] = None
    justificaciones: list[Justificacion] = Field(default_factory=list)
    violaciones: list[Violacion] = Field(default_factory=list)
    resumen: str  # texto corto para la notificación
    feedback: Optional[Feedback] = None  # obligatorio en el ajuste semanal (lo exige la guardia)

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
