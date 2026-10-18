# Servicio completo contra Postgres real, con el LLM falso de tests/agent.

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from agent import servicio
from persistence import repository as repo
from persistence.models import EjecucionAgenteFila
from tests.agent.planes import HOY, contexto_ciclo, feedback_ajuste, plan_valido, resultado_valido
from tests.agent.test_grafo import ModeloFalso, _respuesta, _tool

ANTERIOR = HOY - timedelta(weeks=1)


@pytest.fixture
def sesiones_db(engine):
    fabrica = sessionmaker(bind=engine, expire_on_commit=False)
    yield fabrica
    with engine.begin() as conexion:
        conexion.execute(text("TRUNCATE ejecucion_agente, plan_version, plan, sesion_realizada, ficha_atleta RESTART IDENTITY CASCADE"))


def _entrega(resultado):
    return ModeloFalso(respuestas=[_respuesta(_tool("entregar_resultado", "t1", resultado_json=resultado.model_dump_json()))])


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
    sin_entrega = ModeloFalso(respuestas=[_respuesta(stop="max_tokens")])
    respuesta = servicio.crear_ciclo(sesiones_db, sin_entrega, contexto_ciclo().solicitud, hoy=HOY)

    assert respuesta.plan_id is None
    with sesiones_db() as db:
        assert repo.plan_vigente(db) is None
        ejecucion = db.scalars(select(EjecucionAgenteFila)).one()
    assert (ejecucion.estado, ejecucion.plan_version_id) == ("respuesta_truncada", None)


def test_ajuste_sin_plan_vigente(sesiones_db):
    with pytest.raises(servicio.SinPlanVigente):
        servicio.ajuste_semanal(sesiones_db, ModeloFalso(respuestas=[]), hoy=HOY)


def test_ajuste_semanal_evalua_la_semana_cerrada_y_guarda_la_version_siguiente(sesiones_db):
    vigente = plan_valido(version=1, primera=ANTERIOR, detallar=0)
    with sesiones_db.begin() as db:
        repo.crear_plan(db, vigente, perfil="ejemplo_didactico")

    # La semana cerrada no tuvo ninguna actividad: adherencia 0% → el motor
    # activa EJEMPLO-AJUSTE-001 (repetir_microciclo) y el plan debe citarla.
    ajustado = plan_valido(version=2, primera=ANTERIOR, detallar=1)
    ajustado.mesociclos[0].microciclos[0] = vigente.mesociclos[0].microciclos[0]
    resultado = resultado_valido(ajustado, regla_ids=["EJEMPLO-AJUSTE-001", "EJEMPLO-PROGRESION-001", "EJEMPLO-BLOQUES-001"])
    resultado.feedback = feedback_ajuste()

    respuesta = servicio.ajuste_semanal(sesiones_db, _entrega(resultado), hoy=HOY)

    assert respuesta.evaluacion.accion.regla_id == "EJEMPLO-AJUSTE-001"
    assert (respuesta.ejecucion.estado, respuesta.version) == ("aceptado", 2)
    with sesiones_db() as db:
        historial = repo.historial_versiones(db, respuesta.plan_id)
    assert [(v, m) for v, m, _ in historial] == [(1, "crear_ciclo"), (2, "EJEMPLO-AJUSTE-001: repetir_microciclo")]


def test_perfil_sin_secuencia_para_el_modo_no_llama_al_modelo(sesiones_db, monkeypatch, tmp_path):
    perfil = (servicio.perfiles_dir() / "ejemplo_didactico.yaml").read_text(encoding="utf-8")
    sin_secuencias = perfil[: perfil.index("secuencias_bloques:")]
    (tmp_path / "sin_bloques.yaml").write_text(sin_secuencias, encoding="utf-8")
    monkeypatch.setenv("PB_COACH_PERFILES_DIR", str(tmp_path))

    solicitud = contexto_ciclo().solicitud.model_copy(update={"perfil": "sin_bloques"})
    modelo = ModeloFalso(respuestas=[])
    with pytest.raises(servicio.PerfilIncompleto, match="no define secuencias_bloques"):
        servicio.crear_ciclo(sesiones_db, modelo, solicitud, hoy=HOY)
    assert modelo.llamadas == []


def test_la_misma_semana_no_se_ajusta_dos_veces(sesiones_db):
    vigente = plan_valido(version=1, primera=ANTERIOR, detallar=0)
    with sesiones_db.begin() as db:
        repo.crear_plan(db, vigente, perfil="ejemplo_didactico")

    def ajuste(version):
        plan = plan_valido(version=version, primera=ANTERIOR, detallar=1)
        plan.mesociclos[0].microciclos[0] = vigente.mesociclos[0].microciclos[0]
        regla_ids = ["EJEMPLO-AJUSTE-001", "EJEMPLO-PROGRESION-001", "EJEMPLO-BLOQUES-001"]
        resultado = resultado_valido(plan, regla_ids=regla_ids)
        resultado.feedback = feedback_ajuste()
        return _entrega(resultado)

    primero = servicio.ajuste_semanal(sesiones_db, ajuste(2), hoy=HOY)
    assert primero.version == 2

    # El ciclo se lanza otra vez el mismo día: no se llama al modelo.
    sin_llamadas = ModeloFalso(respuestas=[])
    with pytest.raises(servicio.AjusteYaHecho, match=rf"La semana del {ANTERIOR} ya se ajustó \(versión 2"):
        servicio.ajuste_semanal(sesiones_db, sin_llamadas, hoy=HOY)
    assert sin_llamadas.llamadas == []

    # Pidiéndolo explícitamente, se rehace.
    assert servicio.ajuste_semanal(sesiones_db, ajuste(3), hoy=HOY, forzar=True).version == 3


def test_un_ajuste_fallido_no_cuenta_como_hecho(sesiones_db):
    with sesiones_db.begin() as db:
        repo.crear_plan(db, plan_valido(version=1, primera=ANTERIOR, detallar=0), perfil="ejemplo_didactico")

    servicio.ajuste_semanal(sesiones_db, ModeloFalso(respuestas=[_respuesta(stop="max_tokens")]), hoy=HOY)
    # El primer intento no produjo plan: el segundo sí puede ajustar la semana.
    otro = ModeloFalso(respuestas=[_respuesta(stop="max_tokens")])
    servicio.ajuste_semanal(sesiones_db, otro, hoy=HOY)
    assert len(otro.llamadas) == 1



def test_los_comentarios_del_atleta_quedan_registrados_con_la_ejecucion(sesiones_db):
    from agent.esquemas import ComentarioSesion, ComentariosAtleta

    vigente = plan_valido(version=1, primera=ANTERIOR, detallar=0)
    with sesiones_db.begin() as db:
        repo.crear_plan(db, vigente, perfil="ejemplo_didactico")
    ajustado = plan_valido(version=2, primera=ANTERIOR, detallar=1)
    ajustado.mesociclos[0].microciclos[0] = vigente.mesociclos[0].microciclos[0]
    resultado = resultado_valido(ajustado, regla_ids=["EJEMPLO-AJUSTE-001", "EJEMPLO-PROGRESION-001", "EJEMPLO-BLOQUES-001"])
    resultado.feedback = feedback_ajuste()
    comentarios = ComentariosAtleta(
        general="Viajo el jueves.", por_sesion=[ComentarioSesion(fecha=ANTERIOR, texto="Semana muy cargada en el trabajo.")]
    )

    respuesta = servicio.ajuste_semanal(sesiones_db, _entrega(resultado), hoy=HOY, comentarios=comentarios)

    assert respuesta.ejecucion.resultado.feedback.por_que_cambia.startswith("Sin volumen hecho")
    with sesiones_db() as db:
        registro = db.scalars(select(EjecucionAgenteFila)).one().resultado
    assert registro["comentarios_atleta"]["general"] == "Viajo el jueves."
    assert registro["feedback"]["lo_que_paso"] == "No hubo actividad registrada esta semana."


def test_la_ejecucion_guarda_la_ficha_con_la_que_se_planifico(sesiones_db):
    from core.athlete import Disponibilidad, FichaAtleta

    ficha = FichaAtleta(edad=31, categoria="1", disponibilidad=Disponibilidad(duracion_max_dia=timedelta(hours=10)))
    with sesiones_db.begin() as db:
        repo.guardar_ficha(db, ficha)

    respuesta = servicio.crear_ciclo(sesiones_db, _entrega(resultado_valido()), contexto_ciclo().solicitud, hoy=HOY)

    assert respuesta.version == 1
    with sesiones_db() as db:
        registro = db.scalars(select(EjecucionAgenteFila)).one().resultado
    assert registro["ficha_atleta"]["categoria"] == "1"



def test_el_plan_guardado_lleva_las_pulsaciones_del_atleta(sesiones_db, monkeypatch, tmp_path):
    from core.athlete import FichaAtleta, Umbrales
    from core.training import ZonasFC

    # Perfil de ejemplo con definición de zonas.
    perfil = (servicio.perfiles_dir() / "ejemplo_didactico.yaml").read_text(encoding="utf-8")
    zonas = """
zonas_fc:
  id: "EJEMPLO-ZONAS-001"
  descripcion: "Zonas por umbral aeróbico."
  zonas:
    Z1: { desde: { ancla: "AeT", pct: -20 }, hasta: { ancla: "AeT", pct: -10 } }
    Z2: { desde: { ancla: "AeT", pct: -10 }, hasta: { ancla: "AeT" } }
"""
    (tmp_path / "ejemplo_didactico.yaml").write_text(perfil + zonas, encoding="utf-8")
    monkeypatch.setenv("PB_COACH_PERFILES_DIR", str(tmp_path))
    with sesiones_db.begin() as db:
        repo.guardar_ficha(db, FichaAtleta(edad=31, umbrales=Umbrales(fc_aerobico=149)))

    respuesta = servicio.crear_ciclo(sesiones_db, _entrega(resultado_valido()), contexto_ciclo().solicitud, hoy=HOY)

    with sesiones_db() as db:
        _, plan = repo.plan_vigente(db)
    assert respuesta.version == 1
    assert (plan.rangos_fc[ZonasFC.Z2].minimo, plan.rangos_fc[ZonasFC.Z2].maximo) == (134, 149)
