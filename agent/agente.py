# El agente como grafo de LangGraph: el modelo propone, las tools ejecutan el
# motor y la guardia (dentro de entregar_resultado) decide si el resultado se
# acepta.
#
#   START → modelo ─┬─ pide tools ──▶ herramientas ─┬─ resultado aceptado ─▶ END
#                   │                               └─ si no ──────────────▶ modelo
#                   ├─ no pide tools ▶ recordatorio ────────────────────────▶ modelo
#                   └─ rechazo, truncado o máximo de iteraciones ───────────▶ END
#
# El modelo llega como un BaseChatModel de LangChain (ver modelo.py): el grafo
# no sabe de qué proveedor es. En los tests se usa uno falso, sin red.

import operator
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel

from agent.contexto import ContextoAgente
from agent.herramientas import DEFINICIONES, Herramientas
from agent.modelo import mensaje_sistema, nombre_modelo
from agent.prompts import SYSTEM, primer_mensaje
from agent.resultado import ResultadoAgente

MAX_ITERACIONES = 20
MAX_RECORDATORIOS = 2  # veces que se le recuerda entregar si termina sin hacerlo

RECORDATORIO = "Aún no has entregado el resultado. Termina llamando a entregar_resultado."

# stop_reason de Anthropic / finish_reason de otros proveedores.
_RECHAZO = {"refusal", "content_filter"}
_TRUNCADO = {"max_tokens", "length"}


class EjecucionAgente(BaseModel):
    resultado: Optional[ResultadoAgente] = None
    estado: str  # aceptado | sin_resultado | rechazo_modelo | respuesta_truncada
    detalle: str = ""
    iteraciones: int = 0
    entregas_rechazadas: int = 0
    modelo: str = ""
    tokens_entrada: int = 0
    tokens_salida: int = 0


class EstadoGrafo(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    iteraciones: Annotated[int, operator.add]
    recordatorios: Annotated[int, operator.add]
    tokens_entrada: Annotated[int, operator.add]
    tokens_salida: Annotated[int, operator.add]
    fin: Optional[str]
    detalle: str


def _motivo_parada(respuesta: AIMessage) -> Optional[str]:
    meta = respuesta.response_metadata or {}
    return meta.get("stop_reason") or meta.get("finish_reason")


def construir_grafo(ctx: ContextoAgente, modelo: BaseChatModel, nombre: str, max_iteraciones: int = MAX_ITERACIONES):
    """Grafo compilado para un contexto, y las herramientas (que guardan el
    resultado aceptado por la guardia)."""
    herramientas = Herramientas(ctx)
    modelo_con_tools = modelo.bind_tools(DEFINICIONES, strict=True)
    sistema = mensaje_sistema(SYSTEM, nombre)

    def llamar_modelo(estado: EstadoGrafo) -> dict[str, Any]:
        respuesta = modelo_con_tools.invoke([sistema, *estado["messages"]])
        uso = respuesta.usage_metadata or {}
        cambios: dict[str, Any] = {
            # La respuesta se añade tal cual (con sus bloques de razonamiento):
            # el historial solo crece, nunca se edita.
            "messages": [respuesta],
            "iteraciones": 1,
            "tokens_entrada": uso.get("input_tokens", 0),  # incluye lectura y escritura de caché
            "tokens_salida": uso.get("output_tokens", 0),
        }
        motivo = _motivo_parada(respuesta)
        if motivo in _RECHAZO:
            detalle = (respuesta.response_metadata or {}).get("stop_details") or motivo
            cambios.update(fin="rechazo_modelo", detalle=str(detalle))
        elif motivo in _TRUNCADO:
            cambios.update(fin="respuesta_truncada", detalle="La respuesta superó el máximo de tokens.")
        return cambios

    def ejecutar_herramientas(estado: EstadoGrafo) -> dict[str, Any]:
        ultima: AIMessage = estado["messages"][-1]
        # Todos los resultados de un turno se devuelven juntos.
        mensajes = []
        for llamada in ultima.tool_calls:
            salida = herramientas.ejecutar(llamada["name"], dict(llamada["args"]))
            mensajes.append(
                ToolMessage(
                    content=salida.contenido,
                    tool_call_id=llamada["id"],
                    status="error" if salida.es_error else "success",
                )
            )
        return {"messages": mensajes}

    def recordar(estado: EstadoGrafo) -> dict[str, Any]:
        return {"messages": [HumanMessage(RECORDATORIO)], "recordatorios": 1}

    def tras_modelo(estado: EstadoGrafo) -> str:
        if estado.get("fin"):
            return END
        if estado["messages"][-1].tool_calls:
            return "herramientas"
        if estado["iteraciones"] >= max_iteraciones or estado["recordatorios"] >= MAX_RECORDATORIOS:
            return END
        return "recordatorio"

    def tras_herramientas(estado: EstadoGrafo) -> str:
        if herramientas.resultado_aceptado is not None or estado["iteraciones"] >= max_iteraciones:
            return END
        return "modelo"

    grafo = StateGraph(EstadoGrafo)
    grafo.add_node("modelo", llamar_modelo)
    grafo.add_node("herramientas", ejecutar_herramientas)
    grafo.add_node("recordatorio", recordar)
    grafo.add_edge(START, "modelo")
    grafo.add_conditional_edges("modelo", tras_modelo, ["herramientas", "recordatorio", END])
    grafo.add_conditional_edges("herramientas", tras_herramientas, ["modelo", END])
    grafo.add_edge("recordatorio", "modelo")
    return grafo.compile(), herramientas


def ejecutar_agente(
    ctx: ContextoAgente,
    modelo: BaseChatModel,
    max_iteraciones: int = MAX_ITERACIONES,
    nombre: Optional[str] = None,
) -> EjecucionAgente:
    """Corre el agente sobre un contexto con el modelo dado (de cualquier
    proveedor; en los tests, uno falso)."""
    nombre = nombre or nombre_modelo()
    grafo, herramientas = construir_grafo(ctx, modelo, nombre, max_iteraciones)
    final = grafo.invoke(
        {
            "messages": [HumanMessage(primer_mensaje(ctx))],
            "iteraciones": 0,
            "recordatorios": 0,
            "tokens_entrada": 0,
            "tokens_salida": 0,
            "fin": None,
            "detalle": "",
        },
        # Cada iteración son ~2 pasos del grafo; margen de sobra.
        {"recursion_limit": 4 * max_iteraciones + 10},
    )

    ejecucion = EjecucionAgente(
        estado="sin_resultado",
        iteraciones=final["iteraciones"],
        entregas_rechazadas=herramientas.entregas_rechazadas,
        modelo=nombre,
        tokens_entrada=final["tokens_entrada"],
        tokens_salida=final["tokens_salida"],
    )
    if herramientas.resultado_aceptado is not None:
        ejecucion.resultado = herramientas.resultado_aceptado
        ejecucion.estado = "aceptado"
    elif final.get("fin"):
        ejecucion.estado = final["fin"]
        ejecucion.detalle = final["detalle"]
    elif final["iteraciones"] >= max_iteraciones:
        ejecucion.detalle = f"Se alcanzó el máximo de {max_iteraciones} iteraciones sin un resultado aceptado."
    else:
        ejecucion.detalle = "El modelo terminó sin entregar el resultado."
    return ejecucion
