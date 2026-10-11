# Tools que el LLM puede pedir. El modelo nunca ejecuta nada: devuelve un
# tool_use y este módulo lo ejecuta sobre el contexto en memoria, con las
# funciones puras de engine/.
#
# Los planes viajan como texto JSON (plan_json, resultado_json) y se validan
# con Pydantic aquí: así el error de forma vuelve al modelo con el detalle
# exacto para que corrija, en vez de depender de un esquema rígido en la API.

import json
from datetime import timedelta
from typing import Any, Optional

from pydantic import BaseModel, ValidationError

from agent.contexto import ContextoAgente
from agent.guardia import revisar_resultado
from agent.resultado import Operacion, ResultadoAgente
from core.training import Plan
from core.calculator import inicio_de_semana, resumir_semanas
from core.validator import validar_plan

SEMANAS_HISTORIAL_MAX = 16


def _definicion(nombre: str, descripcion: str, propiedades: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": nombre,
        "description": descripcion,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": propiedades,
            "required": list(propiedades),
            "additionalProperties": False,
        },
    }


DEFINICIONES: list[dict[str, Any]] = [
    _definicion(
        "obtener_perfil",
        "Devuelve el perfil de metodología activo con todas sus reglas y sus IDs. Son las únicas reglas "
        "que existen: cualquier decisión del plan debe apoyarse en ellas y citarlas por su id.",
        {},
    ),
    _definicion(
        "resumen_historial",
        "Volumen realmente entrenado en las últimas N semanas cerradas (lunes a domingo; no incluye la semana en curso): sesiones, km, "
        "duración, desnivel, tiempo por zona de FC y carga (EPOC y sRPE). Ya agregado: nunca sesiones sueltas.",
        {"semanas": {"type": "integer", "description": f"Cuántas semanas hacia atrás, de 1 a {SEMANAS_HISTORIAL_MAX}."}},
    ),
    _definicion(
        "obtener_plan",
        "Devuelve el plan vigente completo (JSON) en sus tres niveles de detalle, o indica que no hay plan.",
        {},
    ),
    _definicion(
        "evaluar_semana",
        "Evaluación de la última semana cerrada hecha por el motor: adherencia, métricas, reglas de ajuste "
        "activadas y la acción que se debe aplicar. Solo en ajuste_semanal. La acción la decide el motor; "
        "tu trabajo es concretarla en el plan.",
        {},
    ),
    _definicion(
        "validar_plan",
        "Valida un plan propuesto contra el perfil. Devuelve las violaciones con su regla_id, las reglas "
        "evaluadas y las que el motor no pudo evaluar. Úsala antes de entregar.",
        {"plan_json": {"type": "string", "description": "El plan completo como JSON, con la forma del esquema Plan."}},
    ),
    _definicion(
        "entregar_resultado",
        "Entrega el resultado final (esquema ResultadoAgente). Pasa por una revisión automática; si devuelve "
        "problemas, corrígelos y vuelve a entregar.",
        {"resultado_json": {"type": "string", "description": "El resultado completo como JSON."}},
    ),
]


class SalidaTool(BaseModel):
    contenido: str
    es_error: bool = False


def _json(modelo: BaseModel | list | dict) -> str:
    if isinstance(modelo, BaseModel):
        return modelo.model_dump_json(exclude_none=True)
    return json.dumps(modelo, ensure_ascii=False, default=str)


def _errores_pydantic(error: ValidationError) -> str:
    lineas = [f"- {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()[:15]]
    return "El JSON no cumple el esquema:\n" + "\n".join(lineas)


class Herramientas:
    """Ejecuta las tools sobre un contexto. Guarda el resultado aceptado."""

    def __init__(self, ctx: ContextoAgente):
        self.ctx = ctx
        self.resultado_aceptado: Optional[ResultadoAgente] = None
        self.entregas_rechazadas = 0

    def ejecutar(self, nombre: str, entrada: dict[str, Any]) -> SalidaTool:
        metodo = getattr(self, f"_tool_{nombre}", None)
        if metodo is None:
            return SalidaTool(contenido=f"La tool {nombre} no existe.", es_error=True)
        try:
            return metodo(**entrada)
        except TypeError as error:
            return SalidaTool(contenido=f"Argumentos inválidos para {nombre}: {error}", es_error=True)

    def _tool_obtener_perfil(self) -> SalidaTool:
        return SalidaTool(contenido=_json(self.ctx.perfil))

    def _tool_resumen_historial(self, semanas: int) -> SalidaTool:
        if not 1 <= semanas <= SEMANAS_HISTORIAL_MAX:
            return SalidaTool(contenido=f"semanas debe estar entre 1 y {SEMANAS_HISTORIAL_MAX}.", es_error=True)
        # Solo semanas cerradas: la semana en curso, a medias, se leería como
        # una caída de volumen que no existe.
        lunes_actual = inicio_de_semana(self.ctx.hoy)
        desde = lunes_actual - timedelta(weeks=semanas)
        resumenes = resumir_semanas(self.ctx.sesiones, desde, lunes_actual - timedelta(days=1))
        return SalidaTool(contenido=_json([r.model_dump(mode="json") for r in resumenes]))

    def _tool_obtener_plan(self) -> SalidaTool:
        if self.ctx.plan_vigente is None:
            return SalidaTool(contenido="No hay plan vigente: se está creando un ciclo nuevo.")
        return SalidaTool(contenido=_json(self.ctx.plan_vigente))

    def _tool_evaluar_semana(self) -> SalidaTool:
        if self.ctx.operacion != Operacion.AJUSTE_SEMANAL:
            return SalidaTool(contenido="evaluar_semana solo aplica en ajuste_semanal.", es_error=True)
        if self.ctx.evaluacion is None:
            return SalidaTool(contenido="No hay ninguna semana cerrada que evaluar todavía.")
        return SalidaTool(contenido=_json(self.ctx.evaluacion))

    def _tool_validar_plan(self, plan_json: str) -> SalidaTool:
        try:
            plan = Plan.model_validate_json(plan_json)
        except ValidationError as error:
            return SalidaTool(contenido=_errores_pydantic(error), es_error=True)
        resultado = validar_plan(plan, self.ctx.perfil)
        return SalidaTool(contenido=_json({**resultado.model_dump(mode="json"), "valido": resultado.valido, "completo": resultado.completo}))

    def _tool_entregar_resultado(self, resultado_json: str) -> SalidaTool:
        try:
            resultado = ResultadoAgente.model_validate_json(resultado_json)
        except ValidationError as error:
            self.entregas_rechazadas += 1
            return SalidaTool(contenido=_errores_pydantic(error), es_error=True)

        problemas = revisar_resultado(resultado, self.ctx)
        if problemas:
            self.entregas_rechazadas += 1
            return SalidaTool(
                contenido="Resultado rechazado por la revisión automática:\n" + "\n".join(f"- {p}" for p in problemas),
                es_error=True,
            )
        self.resultado_aceptado = resultado
        return SalidaTool(contenido="Resultado aceptado.")
