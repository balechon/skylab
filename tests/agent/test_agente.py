# El bucle completo con un cliente falso que devuelve respuestas guionizadas:
# sin red y sin coste.

import json
from types import SimpleNamespace

from pb_coach.agent.agente import MAX_RECORDATORIOS, MODELO, ejecutar_agente
from pb_coach.agent.herramientas import Herramientas
from tests.agent.planes import contexto_ciclo, plan_valido, resultado_valido


def _uso(entrada=1000, salida=200):
    return SimpleNamespace(input_tokens=entrada, output_tokens=salida, cache_read_input_tokens=500, cache_creation_input_tokens=0)


def _tool(nombre, id_, **entrada):
    return SimpleNamespace(type="tool_use", name=nombre, id=id_, input=entrada)


def _respuesta(*bloques, stop="tool_use"):
    return SimpleNamespace(stop_reason=stop, content=list(bloques), usage=_uso())


def _texto(texto):
    return SimpleNamespace(type="text", text=texto)


class ClienteFalso:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._crear))

    def _crear(self, **parametros):
        # Copia superficial de los mensajes: la lista sigue creciendo después.
        self.llamadas.append({**parametros, "messages": list(parametros["messages"])})
        return self.respuestas.pop(0)


RESULTADO_OK = resultado_valido().model_dump_json()
PLAN_OK = plan_valido().model_dump_json()


def test_flujo_completo_aceptado():
    cliente = ClienteFalso(
        [
            _respuesta(_tool("obtener_perfil", "t1"), _tool("resumen_historial", "t2", semanas=8)),
            _respuesta(_tool("validar_plan", "t3", plan_json=PLAN_OK)),
            _respuesta(_tool("entregar_resultado", "t4", resultado_json=RESULTADO_OK)),
        ]
    )
    ejecucion = ejecutar_agente(contexto_ciclo(), cliente)

    assert ejecucion.estado == "aceptado"
    assert ejecucion.resultado.plan == plan_valido()
    assert ejecucion.iteraciones == 3
    assert (ejecucion.tokens_entrada, ejecucion.tokens_salida) == (3 * 1500, 3 * 200)
    # Los dos tool_result del primer turno van en un único mensaje de usuario.
    segundo_turno = cliente.llamadas[1]["messages"]
    assert [r["tool_use_id"] for r in segundo_turno[-1]["content"]] == ["t1", "t2"]


def test_parametros_de_la_llamada():
    cliente = ClienteFalso([_respuesta(_tool("entregar_resultado", "t1", resultado_json=RESULTADO_OK))])
    ejecutar_agente(contexto_ciclo(), cliente)
    parametros = cliente.llamadas[0]
    assert parametros["model"] == MODELO
    assert parametros["fallbacks"] == "default"
    assert parametros["output_config"] == {"effort": "high"}
    assert parametros["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert all(t["strict"] for t in parametros["tools"])


def test_una_entrega_rechazada_vuelve_al_modelo_y_se_corrige():
    malo = json.loads(RESULTADO_OK)
    malo["justificaciones"][0]["regla_ids"] = ["INVENTADA-001"]
    cliente = ClienteFalso(
        [
            _respuesta(_tool("entregar_resultado", "t1", resultado_json=json.dumps(malo))),
            _respuesta(_tool("entregar_resultado", "t2", resultado_json=RESULTADO_OK)),
        ]
    )
    ejecucion = ejecutar_agente(contexto_ciclo(), cliente)

    assert ejecucion.estado == "aceptado"
    assert ejecucion.entregas_rechazadas == 1
    rechazo = cliente.llamadas[1]["messages"][-1]["content"][0]
    assert rechazo["is_error"] and "INVENTADA-001" in rechazo["content"]


def test_si_termina_sin_entregar_se_le_recuerda_y_luego_se_abandona():
    cliente = ClienteFalso([_respuesta(_texto("Listo."), stop="end_turn")] * (MAX_RECORDATORIOS + 1))
    ejecucion = ejecutar_agente(contexto_ciclo(), cliente)
    assert ejecucion.estado == "sin_resultado"
    assert ejecucion.resultado is None
    assert len(cliente.llamadas) == MAX_RECORDATORIOS + 1


def test_rechazo_del_modelo():
    respuesta = _respuesta(stop="refusal")
    respuesta.stop_details = "cyber"
    ejecucion = ejecutar_agente(contexto_ciclo(), ClienteFalso([respuesta]))
    assert (ejecucion.estado, ejecucion.detalle) == ("rechazo_modelo", "cyber")


def test_respuesta_truncada():
    ejecucion = ejecutar_agente(contexto_ciclo(), ClienteFalso([_respuesta(stop="max_tokens")]))
    assert ejecucion.estado == "respuesta_truncada"


def test_maximo_de_iteraciones():
    cliente = ClienteFalso([_respuesta(_tool("obtener_perfil", f"t{i}")) for i in range(3)])
    ejecucion = ejecutar_agente(contexto_ciclo(), cliente, max_iteraciones=3)
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
