from datetime import date, timedelta
from pathlib import Path

import pytest

from core.methodology import (
    AccionAjuste,
    CategoriaRegla,
    CondicionAjuste,
    MetricaAjuste,
    OperadorComparacion,
    OrigenRegla,
    PerfilMetodologia,
    ReglaAjuste,
    RegistroRegla,
)
from core.training import (
    ClaseSesion,
    Microciclo,
    ObjetivosMicrociclo,
    SesionPlanificada,
    SesionRealizada,
    TipoMicrociclo,
    TipoSesion,
    ZonasFC,
)
from core.deviation import (
    ReglaActivada,
    clasificar_sesiones,
    elegir_accion,
    evaluar_semana,
)
from core.loader import cargar_perfil

LUNES = date(2026, 10, 12)
PERFILES_DIR = Path(__file__).parents[2] / "methodology" / "profiles"


def _dia(n: int) -> date:
    return LUNES + timedelta(days=n)


def _planificada(dia, clase, tipo=None, km=8) -> SesionPlanificada:
    if clase == ClaseSesion.DESCANSO:
        return SesionPlanificada(fecha=_dia(dia), clase_sesion=clase)
    return SesionPlanificada(fecha=_dia(dia), clase_sesion=clase, tipo_sesion=tipo, distancia_objetivo_km=km)


def _realizada(dia, minutos=60, km=10.0, zonas=None, rpe=None, clase=None) -> SesionRealizada:
    return SesionRealizada(
        fecha=_dia(dia),
        duracion=timedelta(minutes=minutos),
        distancia_km=km,
        segundos_por_zona=zonas or {},
        rpe=rpe,
        clase_sesion=clase,
    )


PLAN_SEMANA = [
    _planificada(0, ClaseSesion.DESCANSO),
    _planificada(1, ClaseSesion.ESPECIFICO, TipoSesion.SERIES),
    _planificada(3, ClaseSesion.FONDO, TipoSesion.BASE),
    _planificada(6, ClaseSesion.FONDO, TipoSesion.FONDO, km=18),
]


def _micro(sesiones=None, km=None, horas=None, por_clase=None) -> Microciclo:
    return Microciclo(
        fecha_inicio=LUNES,
        fecha_fin=_dia(6),
        tipo_microciclo=TipoMicrociclo.CARGA,
        objetivos=ObjetivosMicrociclo(
            volumen_km=km if km is not None or horas is not None else 40,
            duracion=timedelta(hours=horas) if horas is not None else None,
            sesiones_por_clase=por_clase or {},
        ),
        sesiones=sesiones or [],
    )


def _regla(id_, metrica, operador, valor, accion, **parametros) -> ReglaAjuste:
    return ReglaAjuste(
        id=id_,
        descripcion=f"{metrica} {operador} {valor} -> {accion}",
        condicion=CondicionAjuste(metrica=metrica, operador=operador, valor=valor),
        accion=accion,
        parametros=parametros,
        origen=OrigenRegla.PROPIO,
    )


def _perfil(*reglas_ajuste) -> PerfilMetodologia:
    return PerfilMetodologia(
        autor="TEST",
        fuente="tests",
        version="0",
        deportes_soportados=["running"],
        reglas=[RegistroRegla(id="X-RELLENO-001", categoria=CategoriaRegla.CARGA, descripcion="Relleno.")],
        reglas_ajuste=list(reglas_ajuste),
    )


ADH = MetricaAjuste.ADHERENCIA_VOLUMEN_PCT
RPE = MetricaAjuste.RPE_MEDIO
TEST = MetricaAjuste.MEJORA_TEST_PCT
MENOR, MAYOR = OperadorComparacion.MENOR, OperadorComparacion.MAYOR

REPETIR_SI_BAJA_ADHERENCIA = _regla("X-AJUSTE-001", ADH, MENOR, 70, AccionAjuste.REPETIR_MICROCICLO)
DESCARGA_SI_RPE_ALTO = _regla("X-AJUSTE-002", RPE, MAYOR, 8, AccionAjuste.ADELANTAR_DESCARGA)
PROGRESAR_SI_MEJORA = _regla("X-AJUSTE-003", TEST, MAYOR, 0, AccionAjuste.PROGRESAR, cambio_carga_pct=5)


# ---------- clasificar_sesiones ----------

def test_clasifica_por_sesion_planificada_del_mismo_dia():
    # Un Fondo en montaña con mucho Z4 sigue siendo Fondo: manda lo planificado.
    clasificadas = clasificar_sesiones([_realizada(3, zonas={ZonasFC.Z4: 3000, ZonasFC.Z2: 600})], PLAN_SEMANA)
    assert (clasificadas[0].clase_sesion, clasificadas[0].tipo_sesion) == (ClaseSesion.FONDO, TipoSesion.BASE)


def test_sin_planificada_queda_sin_clasificar_aunque_tenga_zonas():
    clasificadas = clasificar_sesiones([_realizada(2, zonas={ZonasFC.Z4: 3000}), _realizada(4)], PLAN_SEMANA)
    assert all(s.clase_sesion is None for s in clasificadas)


def test_un_dia_de_descanso_planificado_no_clasifica_una_actividad():
    clasificadas = clasificar_sesiones([_realizada(0)], PLAN_SEMANA)
    assert clasificadas[0].clase_sesion is None


def test_cada_planificada_empareja_una_sola_realizada():
    dobles = clasificar_sesiones([_realizada(1), _realizada(1)], PLAN_SEMANA)
    assert [s.clase_sesion for s in dobles] == [ClaseSesion.ESPECIFICO, None]


def test_respeta_las_ya_clasificadas_y_no_modifica_la_entrada():
    original = [_realizada(1, clase=ClaseSesion.FONDO), _realizada(3)]
    copia = [s.model_copy() for s in original]
    clasificadas = clasificar_sesiones(original, PLAN_SEMANA)
    assert clasificadas[0].clase_sesion == ClaseSesion.FONDO
    assert original == copia


# ---------- adherencia ----------

def test_adherencia_volumen_en_km():
    evaluacion = evaluar_semana(_micro(km=40), [_realizada(1, km=10), _realizada(3, km=20)], _perfil())
    assert evaluacion.metricas[ADH] == 75.0


def test_adherencia_volumen_en_horas_si_el_objetivo_es_tiempo():
    evaluacion = evaluar_semana(_micro(horas=5), [_realizada(1, minutos=90), _realizada(3, minutos=150)], _perfil())
    assert evaluacion.metricas[ADH] == 80.0


def test_adherencia_sesiones_en_semana_detallada():
    # 3 sesiones con carga previstas; hay actividad 2 de esos días.
    evaluacion = evaluar_semana(_micro(sesiones=PLAN_SEMANA), [_realizada(1), _realizada(6), _realizada(4)], _perfil())
    assert evaluacion.metricas[MetricaAjuste.ADHERENCIA_SESIONES_PCT] == 66.7


def test_adherencia_sesiones_con_solo_objetivos():
    micro = _micro(por_clase={ClaseSesion.FONDO: 3, ClaseSesion.ESPECIFICO: 1, ClaseSesion.DESCANSO: 2})
    evaluacion = evaluar_semana(micro, [_realizada(1), _realizada(3), _realizada(5)], _perfil())
    assert evaluacion.metricas[MetricaAjuste.ADHERENCIA_SESIONES_PCT] == 75.0


def test_ignora_actividades_fuera_de_la_semana():
    evaluacion = evaluar_semana(_micro(km=40), [_realizada(-1, km=30), _realizada(1, km=20)], _perfil())
    assert evaluacion.metricas[ADH] == 50.0


def test_sin_rpe_la_metrica_no_esta_disponible():
    evaluacion = evaluar_semana(_micro(), [_realizada(1)], _perfil())
    assert RPE in evaluacion.metricas_no_disponibles


# ---------- reglas de ajuste ----------

def test_sin_reglas_activadas_se_sigue_el_plan():
    evaluacion = evaluar_semana(_micro(km=40), [_realizada(1, km=40)], _perfil(REPETIR_SI_BAJA_ADHERENCIA))
    assert evaluacion.accion is None
    assert evaluacion.reglas_activadas == []


def test_regla_activada_cita_metrica_y_umbral():
    evaluacion = evaluar_semana(_micro(km=40), [_realizada(1, km=20)], _perfil(REPETIR_SI_BAJA_ADHERENCIA))
    accion = evaluacion.accion
    assert (accion.regla_id, accion.accion) == ("X-AJUSTE-001", AccionAjuste.REPETIR_MICROCICLO)
    assert (accion.valor_metrica, accion.umbral) == (50.0, "< 70")


def test_con_varias_activadas_gana_la_mas_conservadora_y_se_informan_todas():
    realizadas = [_realizada(1, km=10, rpe=9), _realizada(3, km=10, rpe=9)]  # adherencia 50%, RPE 9
    evaluacion = evaluar_semana(
        _micro(km=40), realizadas, _perfil(REPETIR_SI_BAJA_ADHERENCIA, DESCARGA_SI_RPE_ALTO)
    )
    assert evaluacion.accion.accion == AccionAjuste.ADELANTAR_DESCARGA
    assert {r.regla_id for r in evaluacion.reglas_activadas} == {"X-AJUSTE-001", "X-AJUSTE-002"}


def test_metrica_ausente_deja_la_regla_como_no_evaluable():
    evaluacion = evaluar_semana(_micro(), [_realizada(1)], _perfil(PROGRESAR_SI_MEJORA))
    assert evaluacion.accion is None
    assert evaluacion.reglas_no_evaluables[0].regla_id == "X-AJUSTE-003"


def test_metricas_externas_permiten_evaluar_progreso():
    evaluacion = evaluar_semana(_micro(km=40), [_realizada(1, km=40)], _perfil(PROGRESAR_SI_MEJORA), {TEST: 3.5})
    assert evaluacion.accion.accion == AccionAjuste.PROGRESAR
    assert evaluacion.accion.parametros == {"cambio_carga_pct": 5}


@pytest.mark.parametrize(
    "acciones, ganadora",
    [
        ([AccionAjuste.PROGRESAR, AccionAjuste.MANTENER], AccionAjuste.MANTENER),
        ([AccionAjuste.EXTENDER_MESOCICLO, AccionAjuste.REPETIR_MICROCICLO], AccionAjuste.REPETIR_MICROCICLO),
        ([AccionAjuste.ADELANTAR_DESCARGA, AccionAjuste.REDUCIR_CARGA], AccionAjuste.REDUCIR_CARGA),
    ],
)
def test_prioridad_de_acciones(acciones, ganadora):
    activadas = [
        ReglaActivada(regla_id=f"R{i}", accion=a, parametros={}, metrica=ADH, valor_metrica=0, umbral="< 0")
        for i, a in enumerate(acciones)
    ]
    assert elegir_accion(activadas).accion == ganadora


# ---------- integración con el perfil didáctico ----------

def test_semana_floja_con_el_perfil_didactico_repite_microciclo():
    perfil = cargar_perfil(PERFILES_DIR / "ejemplo_didactico.yaml")
    evaluacion = evaluar_semana(_micro(km=40, sesiones=PLAN_SEMANA), [_realizada(1, km=8), _realizada(3, km=10)], perfil)
    assert evaluacion.accion.regla_id == "EJEMPLO-AJUSTE-001"
    assert evaluacion.accion.accion == AccionAjuste.REPETIR_MICROCICLO
    # EJEMPLO-AJUSTE-002 depende de un test que esta semana no hubo.
    assert [r.regla_id for r in evaluacion.reglas_no_evaluables] == ["EJEMPLO-AJUSTE-002"]
