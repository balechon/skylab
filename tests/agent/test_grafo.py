# El grafo completo con un modelo de chat falso que devuelve respuestas
# guionizadas: sin red y sin coste. Es un BaseChatModel de LangChain, igual
# que el real, así que se prueba el mismo camino que en producción.

import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from agent.grafo import MAX_RECORDATORIOS, ejecutar_agente
from agent.herramientas import Herramientas
from tests.agent.planes import contexto_ciclo, plan_valido, resultado_valido


class ModeloFalso(BaseChatModel):
    """Devuelve las respuestas en orden y registra lo que recibe."""

    respuestas: list[AIMessage]
    llamadas: list[list[Any]] = Field(default_factory=list)
    enlace: dict[str, Any] = Field(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "falso"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.llamadas.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.respuestas.pop(0))])

    def bind_tools(self, tools, **kwargs):
        self.enlace = {"tools": tools, **kwargs}
        return self


def _tool(nombre, id_, **args):
    return {"name": nombre, "args": args, "id": id_, "type": "tool_call"}


def _respuesta(*llamadas, stop="tool_use", texto="", **meta):
    return AIMessage(
        content=texto,
        tool_calls=list(llamadas),
        usage_metadata={"input_tokens": 1500, "output_tokens": 200, "total_tokens": 1700},
        response_metadata={"stop_reason": stop, **meta},
    )


RESULTADO_OK = resultado_valido().model_dump_json()
PLAN_OK = plan_valido().model_dump_json()


def test_flujo_completo_aceptado():
    modelo = ModeloFalso(
        respuestas=[
            _respuesta(_tool("obtener_perfil", "t1"), _tool("resumen_historial", "t2", semanas=8)),
            _respuesta(_tool("validar_plan", "t3", plan_json=PLAN_OK)),
            _respuesta(_tool("entregar_resultado", "t4", resultado_json=RESULTADO_OK)),
        ]
    )
    ejecucion = ejecutar_agente(contexto_ciclo(), modelo)

    assert ejecucion.estado == "aceptado"
    assert ejecucion.resultado.plan == plan_valido()
    assert ejecucion.iteraciones == 3
    assert (ejecucion.tokens_entrada, ejecucion.tokens_salida) == (3 * 1500, 3 * 200)
    # Las dos tools del primer turno se responden juntas antes de volver al modelo.
    segundo_turno = modelo.llamadas[1]
    assert all(isinstance(m, ToolMessage) for m in segundo_turno[-2:])
    assert [m.tool_call_id for m in segundo_turno[-2:]] == ["t1", "t2"]


def test_el_modelo_recibe_system_cacheado_y_tools_estrictas():
    modelo = ModeloFalso(respuestas=[_respuesta(_tool("entregar_resultado", "t1", resultado_json=RESULTADO_OK))])
    ejecucion = ejecutar_agente(contexto_ciclo(), modelo)

    sistema = modelo.llamadas[0][0]
    assert isinstance(sistema, SystemMessage)
    assert sistema.content[0]["cache_control"] == {"type": "ephemeral"}  # proveedor por defecto: Anthropic
    assert modelo.enlace["strict"] is True
    assert [t["name"] for t in modelo.enlace["tools"]] == [
        "obtener_perfil",
        "resumen_historial",
        "obtener_plan",
        "evaluar_semana",
        "validar_plan",
        "entregar_resultado",
    ]
    assert ejecucion.modelo == "anthropic:claude-opus-5-5"


def test_con_otro_proveedor_el_system_va_como_texto_plano():
    modelo = ModeloFalso(respuestas=[_respuesta(_tool("entregar_resultado", "t1", resultado_json=RESULTADO_OK))])
    ejecucion = ejecutar_agente(contexto_ciclo(), modelo, nombre="openai:otro-modelo")
    assert isinstance(modelo.llamadas[0][0].content, str)
    assert ejecucion.modelo == "openai:otro-modelo"


def test_una_entrega_rechazada_vuelve_al_modelo_y_se_corrige():
    malo = json.loads(RESULTADO_OK)
    malo["justificaciones"][0]["regla_ids"] = ["INVENTADA-001"]
    modelo = ModeloFalso(
        respuestas=[
            _respuesta(_tool("entregar_resultado", "t1", resultado_json=json.dumps(malo))),
            _respuesta(_tool("entregar_resultado", "t2", resultado_json=RESULTADO_OK)),
        ]
    )
    ejecucion = ejecutar_agente(contexto_ciclo(), modelo)

    assert ejecucion.estado == "aceptado"
    assert ejecucion.entregas_rechazadas == 1
    rechazo = modelo.llamadas[1][-1]
    assert rechazo.status == "error" and "INVENTADA-001" in rechazo.content


def test_si_termina_sin_entregar_se_le_recuerda_y_luego_se_abandona():
    modelo = ModeloFalso(respuestas=[_respuesta(stop="end_turn", texto="Listo.") for _ in range(MAX_RECORDATORIOS + 1)])
    ejecucion = ejecutar_agente(contexto_ciclo(), modelo)
    assert ejecucion.estado == "sin_resultado"
    assert ejecucion.resultado is None
    assert len(modelo.llamadas) == MAX_RECORDATORIOS + 1
    assert "terminó sin entregar" in ejecucion.detalle


def test_rechazo_del_modelo():
    modelo = ModeloFalso(respuestas=[_respuesta(stop="refusal", stop_details="cyber")])
    ejecucion = ejecutar_agente(contexto_ciclo(), modelo)
    assert (ejecucion.estado, ejecucion.detalle) == ("rechazo_modelo", "cyber")


def test_respuesta_truncada():
    ejecucion = ejecutar_agente(contexto_ciclo(), ModeloFalso(respuestas=[_respuesta(stop="max_tokens")]))
    assert ejecucion.estado == "respuesta_truncada"


def test_truncado_de_otro_proveedor_se_reconoce():
    respuesta = AIMessage(content="", response_metadata={"finish_reason": "length"})
    ejecucion = ejecutar_agente(contexto_ciclo(), ModeloFalso(respuestas=[respuesta]), nombre="openai:otro-modelo")
    assert ejecucion.estado == "respuesta_truncada"


def test_maximo_de_iteraciones():
    modelo = ModeloFalso(respuestas=[_respuesta(_tool("obtener_perfil", f"t{i}")) for i in range(3)])
    ejecucion = ejecutar_agente(contexto_ciclo(), modelo, max_iteraciones=3)
    assert ejecucion.estado == "sin_resultado"
    assert "máximo de 3 iteraciones" in ejecucion.detalle


# ---------- tools sueltas ----------

def test_validar_plan_con_json_roto_devuelve_el_error_al_modelo():
    salida = Herramientas(contexto_ciclo()).ejecutar("validar_plan", {"plan_json": '{"modo": "Construcción"}'})
    assert salida.es_error and "fecha_inicio" in salida.contenido


def test_resumen_historial_limita_las_semanas():
    herramientas = Herramientas(contexto_ciclo())
    assert herramientas.ejecutar("resumen_historial", {"semanas": 40}).es_error
    # HOY es lunes 12/10: las dos semanas cerradas son 28/09–04/10 y 05/10–11/10.
    semanas = json.loads(herramientas.ejecutar("resumen_historial", {"semanas": 2}).contenido)
    assert [s["fecha_inicio"] for s in semanas] == ["2026-09-28", "2026-10-05"]
    assert [s["numero_sesiones"] for s in semanas] == [1, 3]


def test_tool_desconocida():
    assert Herramientas(contexto_ciclo()).ejecutar("borrar_todo", {}).es_error


def test_evaluar_semana_no_aplica_al_crear_ciclo():
    assert Herramientas(contexto_ciclo()).ejecutar("evaluar_semana", {}).es_error
