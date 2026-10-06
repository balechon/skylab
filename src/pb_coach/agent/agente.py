# Bucle del agente: Claude propone, las tools ejecutan el motor y la guardia
# decide si el resultado se acepta.
#
# Bucle manual (no el Tool Runner del SDK) para controlar explícitamente:
# el número de iteraciones, la revisión de cada entrega, los rechazos del
# modelo (stop_reason "refusal") y las respuestas truncadas, y para poder
# probarlo con un cliente falso, sin red.

from typing import Any, Optional

from pydantic import BaseModel

from pb_coach.agent.contexto import ContextoAgente
from pb_coach.agent.herramientas import DEFINICIONES, Herramientas
from pb_coach.agent.prompts import SYSTEM, primer_mensaje
from pb_coach.agent.resultado import ResultadoAgente

MODELO = "claude-opus-5-5"
MAX_TOKENS = 16000
MAX_ITERACIONES = 20
MAX_RECORDATORIOS = 2  # veces que se le recuerda entregar si termina sin hacerlo

RECORDATORIO = "Aún no has entregado el resultado. Termina llamando a entregar_resultado."


class EjecucionAgente(BaseModel):
    resultado: Optional[ResultadoAgente] = None
    estado: str  # aceptado | sin_resultado | rechazo_modelo | respuesta_truncada
    detalle: str = ""
    iteraciones: int = 0
    entregas_rechazadas: int = 0
    modelo: str = MODELO
    tokens_entrada: int = 0
    tokens_salida: int = 0


def _parametros(mensajes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": MODELO,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "tools": DEFINICIONES,
        "messages": mensajes,
        "output_config": {"effort": "high"},
        # Si un clasificador de seguridad rechaza la petición, la API la
        # reintenta en el modelo de respaldo que corresponda.
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
    }


def ejecutar_agente(ctx: ContextoAgente, cliente: Any, max_iteraciones: int = MAX_ITERACIONES) -> EjecucionAgente:
    """Corre el agente sobre un contexto. `cliente` es un anthropic.Anthropic
    (o un falso con el mismo `beta.messages.create`)."""
    herramientas = Herramientas(ctx)
    mensajes: list[dict[str, Any]] = [{"role": "user", "content": primer_mensaje(ctx)}]
    ejecucion = EjecucionAgente(estado="sin_resultado")
    recordatorios = 0

    for iteracion in range(1, max_iteraciones + 1):
        ejecucion.iteraciones = iteracion
        respuesta = cliente.beta.messages.create(**_parametros(mensajes))
        uso = respuesta.usage
        ejecucion.tokens_entrada += (
            uso.input_tokens + (uso.cache_read_input_tokens or 0) + (uso.cache_creation_input_tokens or 0)
        )
        ejecucion.tokens_salida += uso.output_tokens

        if respuesta.stop_reason == "refusal":
            ejecucion.estado = "rechazo_modelo"
            ejecucion.detalle = str(getattr(respuesta, "stop_details", "") or "")
            break
        if respuesta.stop_reason == "max_tokens":
            ejecucion.estado = "respuesta_truncada"
            ejecucion.detalle = f"La respuesta superó {MAX_TOKENS} tokens."
            break

        # Se añade la respuesta tal cual (incluidos los bloques de thinking):
        # el historial solo crece, nunca se edita.
        mensajes.append({"role": "assistant", "content": respuesta.content})

        llamadas = [b for b in respuesta.content if b.type == "tool_use"]
        if not llamadas:
            if recordatorios >= MAX_RECORDATORIOS:
                ejecucion.detalle = "El modelo terminó sin entregar el resultado."
                break
            recordatorios += 1
            mensajes.append({"role": "user", "content": RECORDATORIO})
            continue

        resultados = []
        for llamada in llamadas:
            salida = herramientas.ejecutar(llamada.name, dict(llamada.input))
            resultados.append(
                {
                    "type": "tool_result",
                    "tool_use_id": llamada.id,
                    "content": salida.contenido,
                    "is_error": salida.es_error,
                }
            )
        # Todos los resultados de un turno van en un único mensaje.
        mensajes.append({"role": "user", "content": resultados})

        if herramientas.resultado_aceptado is not None:
            ejecucion.resultado = herramientas.resultado_aceptado
            ejecucion.estado = "aceptado"
            break
    else:
        ejecucion.detalle = f"Se alcanzó el máximo de {max_iteraciones} iteraciones sin un resultado aceptado."

    ejecucion.entregas_rechazadas = herramientas.entregas_rechazadas
    return ejecucion
