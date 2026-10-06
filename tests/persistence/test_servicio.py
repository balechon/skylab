# Servicio completo contra Postgres real, con el LLM falso de tests/agent.

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from pb_coach.agent import servicio
from pb_coach.persistence import repository as repo
from pb_coach.persistence.models import EjecucionAgenteFila
from tests.agent.planes import HOY, contexto_ciclo, plan_valido, resultado_valido
from tests.agent.test_agente import ClienteFalso, _respuesta, _tool

ANTERIOR = HOY - timedelta(weeks=1)


@pytest.fixture
def sesiones_db(engine):
    fabrica = sessionmaker(bind=engine, expire_on_commit=False)
    yield fabrica
    with engine.begin() as conexion:
        conexion.execute(text("TRUNCATE ejecucion_agente, plan_version, plan, sesion_realizada RESTART IDENTITY CASCADE"))


def _entrega(resultado):
    return ClienteFalso([_respuesta(_tool("entregar_resultado", "t1", resultado_json=resultado.model_dump_json()))])


def test_crear_ciclo_guarda_la_version_1_y_la_ejecucion(sesiones_db):
    respuesta = servicio.crear_ciclo(sesiones_db, _entrega(resultado_valido()), contexto_ciclo().solicitud, hoy=HOY)

    assert (respuesta.ejecucion.estado, respuesta.version) == ("aceptado", 1)
    with sesiones_db() as db:
        assert repo.plan_vigente(db) == (respuesta.plan_id, plan_valido())
        ejecucion = db.scalars(select(EjecucionAgenteFila)).one()
    assert (ejecucion.operacion, ejecucion.estado) == ("crear_ciclo", "plan_valido")
    assert ejecucion.plan_version_id is not None
    assert ejecucion.tokens_entrada == 1500


def test_si_el_agente_falla_no_se_guarda_plan_pero_si_la_ejecucion(sesiones_db):
    sin_entrega = ClienteFalso([_respuesta(stop="max_tokens")])
    respuesta = servicio.crear_ciclo(sesiones_db, sin_entrega, contexto_ciclo().solicitud, hoy=HOY)

    assert respuesta.plan_id is None
    with sesiones_db() as db:
        assert repo.plan_vigente(db) is None
        ejecucion = db.scalars(select(EjecucionAgenteFila)).one()
    assert (ejecucion.estado, ejecucion.plan_version_id) == ("respuesta_truncada", None)


def test_ajuste_sin_plan_vigente(sesiones_db):
    with pytest.raises(servicio.SinPlanVigente):
        servicio.ajuste_semanal(sesiones_db, ClienteFalso([]), hoy=HOY)


def test_ajuste_semanal_evalua_la_semana_cerrada_y_guarda_la_version_siguiente(sesiones_db):
    vigente = plan_valido(version=1, primera=ANTERIOR, detallar=0)
    with sesiones_db.begin() as db:
        repo.crear_plan(db, vigente, perfil="ejemplo_didactico")

    # La semana cerrada no tuvo ninguna actividad: adherencia 0% → el motor
    # activa EJEMPLO-AJUSTE-001 (repetir_microciclo) y el plan debe citarla.
    ajustado = plan_valido(version=2, primera=ANTERIOR, detallar=1)
    ajustado.mesociclos[0].microciclos[0] = vigente.mesociclos[0].microciclos[0]
    resultado = resultado_valido(ajustado, regla_ids=["EJEMPLO-AJUSTE-001", "EJEMPLO-PROGRESION-001"])

    respuesta = servicio.ajuste_semanal(sesiones_db, _entrega(resultado), hoy=HOY)

    assert respuesta.evaluacion.accion.regla_id == "EJEMPLO-AJUSTE-001"
    assert (respuesta.ejecucion.estado, respuesta.version) == ("aceptado", 2)
    with sesiones_db() as db:
        historial = repo.historial_versiones(db, respuesta.plan_id)
    assert [(v, m) for v, m, _ in historial] == [(1, "crear_ciclo"), (2, "EJEMPLO-AJUSTE-001: repetir_microciclo")]
