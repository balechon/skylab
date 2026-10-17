from datetime import timedelta

from agent.esquemas import ContextoAgente, EstadoResultado, Operacion, ResultadoAgente
from agent.guardia import revisar_resultado
from core.methodology import AccionAjuste, MetricaAjuste
from core.training import ModoPlan, ObjetivoMesociclo
from core.calculator import resumir_periodo
from core.deviation import EvaluacionSemana, ReglaActivada
from core.validator import Violacion
from tests.agent.planes import HOY, PERFIL, contexto_ciclo, plan_valido, resultado_valido


def test_un_plan_correcto_no_tiene_objeciones():
    assert revisar_resultado(resultado_valido(), contexto_ciclo()) == []


def test_rechaza_reglas_inventadas():
    problemas = revisar_resultado(resultado_valido(regla_ids=["DANIELS-VDOT-001"]), contexto_ciclo())
    assert any("no existen en el perfil" in p and "DANIELS-VDOT-001" in p for p in problemas)


def test_rechaza_un_plan_que_incumple_el_perfil():
    plan = plan_valido()
    plan.mesociclos[0].microciclos[1].objetivos.volumen_km = 60  # +50% sobre 40
    problemas = revisar_resultado(resultado_valido(plan), contexto_ciclo())
    assert any("EJEMPLO-PROGRESION-001" in p for p in problemas)


def test_la_proxima_semana_debe_estar_detallada():
    problemas = revisar_resultado(resultado_valido(plan_valido(detallar=1)), contexto_ciclo())
    assert any("debe tener sesiones concretas" in p for p in problemas)


def test_ciclo_nuevo_debe_respetar_la_solicitud():
    ctx = contexto_ciclo()
    ctx.solicitud.modo = ModoPlan.COMPETICION
    problemas = revisar_resultado(resultado_valido(plan_valido(version=2)), ctx)
    assert any("versión 1" in p for p in problemas)
    assert any("modo Competición" in p for p in problemas)


def test_sin_solucion_solo_exige_reglas_reales():
    resultado = ResultadoAgente(
        estado=EstadoResultado.SIN_SOLUCION,
        violaciones=[Violacion(regla_id="EJEMPLO-GLOBAL-002", mensaje="No hay semanas suficientes.")],
        resumen="No hay plan posible.",
    )
    assert revisar_resultado(resultado, contexto_ciclo()) == []


# ---------- ajuste semanal ----------

ANTERIOR = HOY - timedelta(weeks=1)


def _contexto_ajuste(accion=None) -> ContextoAgente:
    evaluacion = None
    if accion is not None:
        evaluacion = EvaluacionSemana(
            resumen=resumir_periodo([], ANTERIOR, HOY - timedelta(days=1)),
            metricas={MetricaAjuste.ADHERENCIA_VOLUMEN_PCT: 45.0},
            metricas_no_disponibles=[],
            accion=accion,
            reglas_activadas=[accion],
        )
    return ContextoAgente(
        operacion=Operacion.AJUSTE_SEMANAL,
        hoy=HOY,
        nombre_perfil="ejemplo_didactico",
        perfil=PERFIL,
        sesiones=[],
        plan_vigente=plan_valido(version=3, primera=ANTERIOR, detallar=0),
        evaluacion=evaluacion,
    )


def _ajuste(version=4):
    # Misma estructura que el vigente, con la semana de hoy (índice 1) detallada.
    plan = plan_valido(version=version, primera=ANTERIOR, detallar=1)
    plan.mesociclos[0].microciclos[0] = _contexto_ajuste().plan_vigente.mesociclos[0].microciclos[0]
    return plan


def test_ajuste_correcto_no_tiene_objeciones():
    assert revisar_resultado(resultado_valido(_ajuste()), _contexto_ajuste()) == []


def test_ajuste_debe_ser_la_version_siguiente():
    problemas = revisar_resultado(resultado_valido(_ajuste(version=6)), _contexto_ajuste())
    assert any("versión 4" in p for p in problemas)


def test_ajuste_no_puede_tocar_semanas_pasadas():
    plan = _ajuste()
    plan.mesociclos[0].microciclos[0].objetivos.volumen_km = 41
    problemas = revisar_resultado(resultado_valido(plan), _contexto_ajuste())
    assert any(f"La semana del {ANTERIOR} ya pasó" in p for p in problemas)


def test_ajuste_debe_aplicar_y_citar_la_accion_del_motor():
    accion = ReglaActivada(
        regla_id="EJEMPLO-AJUSTE-001",
        accion=AccionAjuste.REPETIR_MICROCICLO,
        parametros={},
        metrica=MetricaAjuste.ADHERENCIA_VOLUMEN_PCT,
        valor_metrica=45.0,
        umbral="< 70",
    )
    ctx = _contexto_ajuste(accion)
    sin_citar = revisar_resultado(resultado_valido(_ajuste()), ctx)
    assert any("EJEMPLO-AJUSTE-001" in p and "repetir_microciclo" in p for p in sin_citar)

    citando = resultado_valido(_ajuste(), regla_ids=["EJEMPLO-PROGRESION-001", "EJEMPLO-BLOQUES-001", "EJEMPLO-AJUSTE-001"])
    assert revisar_resultado(citando, ctx) == []


# ---------- secuencia de bloques ----------

def test_rechaza_bloques_que_no_siguen_la_secuencia():
    plan = plan_valido()
    plan.mesociclos[1].objetivo = ObjetivoMesociclo.UMBRAL  # la prueba real eligió esto sin regla
    problemas = revisar_resultado(resultado_valido(plan), contexto_ciclo())
    assert any("EJEMPLO-BLOQUES-001" in p and "Umbral" in p for p in problemas)


def test_exige_citar_la_secuencia():
    problemas = revisar_resultado(resultado_valido(regla_ids=["EJEMPLO-PROGRESION-001"]), contexto_ciclo())
    assert any("citando EJEMPLO-BLOQUES-001" in p for p in problemas)


def test_sin_secuencia_para_el_modo_se_rechaza():
    perfil = PERFIL.model_copy(update={"secuencias_bloques": []})
    problemas = revisar_resultado(resultado_valido(regla_ids=["EJEMPLO-PROGRESION-001"]), contexto_ciclo(perfil=perfil))
    assert any("no define la secuencia de bloques" in p for p in problemas)


# ---------- el bloque en curso, completo ----------

def test_un_bloque_futuro_puede_seguir_siendo_esqueleto():
    # plan_valido(): Base con sus 4 semanas y Fuerza como esqueleto.
    assert revisar_resultado(resultado_valido(), contexto_ciclo()) == []


def test_al_entrar_en_un_bloque_esqueleto_se_rechaza():
    # Cuatro semanas después, el bloque en curso es Fuerza, que sigue siendo esqueleto.
    plan = plan_valido()
    ctx = contexto_ciclo(hoy=plan.mesociclos[1].fecha_inicio)
    problemas = revisar_resultado(resultado_valido(plan), ctx)
    assert any("es solo esqueleto" in p and "Fuerza y economía" in p for p in problemas)


def test_un_hueco_en_el_bloque_en_curso_se_rechaza():
    plan = plan_valido()
    del plan.mesociclos[0].microciclos[2]  # falta la tercera semana de Base
    problemas = revisar_resultado(resultado_valido(plan), contexto_ciclo())
    tercera = plan.mesociclos[0].fecha_inicio + timedelta(weeks=2)
    assert any(f"no tiene semanas definidas entre {tercera}" in p for p in problemas)


def test_las_ultimas_semanas_sin_definir_se_rechazan():
    plan = plan_valido()
    del plan.mesociclos[0].microciclos[-1]  # falta la descarga, la última semana del bloque
    problemas = revisar_resultado(resultado_valido(plan), contexto_ciclo())
    assert any(f"y {plan.mesociclos[0].fecha_fin}" in p for p in problemas)
