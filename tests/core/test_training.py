from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from core.training import (
    Carrera,
    Intervalos,
    ClaseSesion,
    Mesociclo,
    Microciclo,
    ModoPlan,
    ObjetivoMesociclo,
    ObjetivosMicrociclo,
    Plan,
    SesionPlanificada,
    SesionRealizada,
    Terreno,
    TipoMicrociclo,
    TipoSesion,
    ZonasFC,
)


def _objetivos() -> ObjetivosMicrociclo:
    return ObjetivosMicrociclo(
        volumen_km=40,
        sesiones_por_clase={ClaseSesion.FONDO: 3, ClaseSesion.ESPECIFICO: 1, ClaseSesion.DESCANSO: 1},
    )


def _rodaje(fecha: date) -> SesionPlanificada:
    return SesionPlanificada(
        fecha=fecha,
        clase_sesion=ClaseSesion.FONDO,
        tipo_sesion=TipoSesion.BASE,
        terreno=Terreno.CAMINO_NO_TECNICO,
        distancia_objetivo_km=10,
        zona_fc_objetivo=ZonasFC.Z2,
    )


def _microciclo(inicio: date, sesiones=None) -> Microciclo:
    return Microciclo(
        fecha_inicio=inicio,
        fecha_fin=inicio + timedelta(days=6),
        tipo_microciclo=TipoMicrociclo.CARGA,
        objetivos=_objetivos(),
        sesiones=sesiones or [],
    )


def _mesociclo(inicio: date, fin: date, microciclos=None) -> Mesociclo:
    return Mesociclo(
        objetivo=ObjetivoMesociclo.BASE_AEROBICA,
        fecha_inicio=inicio,
        fecha_fin=fin,
        microciclos=microciclos or [],
    )


# ---------- SesionPlanificada ----------

def test_sesion_planificada_valida_especifico_con_series():
    sesion = SesionPlanificada(
        fecha=date(2026, 10, 13),
        clase_sesion=ClaseSesion.ESPECIFICO,
        tipo_sesion=TipoSesion.SERIES,
        terreno=Terreno.PISTA,
        distancia_objetivo_km=8,
        zona_fc_objetivo=ZonasFC.Z4,
        descripcion="6x800 m a ritmo de 5K",
        intervalos=Intervalos(repeticiones=6, trabajo=timedelta(minutes=3), recuperacion=timedelta(minutes=2)),
    )
    assert sesion.tipo_sesion == TipoSesion.SERIES


def test_sesion_planificada_rechaza_especifico_con_tipo_no_permitido():
    with pytest.raises(ValidationError):
        SesionPlanificada(
            fecha=date(2026, 10, 13),
            clase_sesion=ClaseSesion.ESPECIFICO,
            tipo_sesion=TipoSesion.BASE,
            distancia_objetivo_km=8,
        )


def test_sesion_planificada_rechaza_descanso_con_tipo_sesion():
    with pytest.raises(ValidationError):
        SesionPlanificada(
            fecha=date(2026, 10, 12),
            clase_sesion=ClaseSesion.DESCANSO,
            tipo_sesion=TipoSesion.SERIES,
        )


def test_sesion_planificada_descanso_valido_sin_carga():
    sesion = SesionPlanificada(fecha=date(2026, 10, 12), clase_sesion=ClaseSesion.DESCANSO)
    assert sesion.distancia_objetivo_km is None


def test_sesion_planificada_rechaza_descanso_con_distancia():
    with pytest.raises(ValidationError, match="Descanso"):
        SesionPlanificada(
            fecha=date(2026, 10, 12),
            clase_sesion=ClaseSesion.DESCANSO,
            distancia_objetivo_km=5,
        )


def test_sesion_planificada_con_carga_necesita_distancia_o_duracion():
    with pytest.raises(ValidationError, match="distancia_objetivo_km o duracion_objetivo"):
        SesionPlanificada(
            fecha=date(2026, 10, 14),
            clase_sesion=ClaseSesion.FONDO,
            tipo_sesion=TipoSesion.FONDO,
        )


def test_sesion_planificada_por_duracion_es_valida():
    # En trail a menudo se prescribe por tiempo, no por distancia.
    sesion = SesionPlanificada(
        fecha=date(2026, 10, 18),
        clase_sesion=ClaseSesion.FONDO,
        tipo_sesion=TipoSesion.FONDO,
        terreno=Terreno.SENDERO_TECNICO,
        duracion_objetivo=timedelta(hours=2),
        desnivel_positivo_objetivo_m=800,
    )
    assert sesion.duracion_objetivo == timedelta(hours=2)


# ---------- SesionRealizada ----------

def test_sesion_realizada_sin_clasificar_es_valida():
    # Tal como llega de Garmin: sin clase ni tipo, los deduce engine/.
    sesion = SesionRealizada(
        fecha=date(2026, 10, 13),
        duracion=timedelta(minutes=52),
        distancia_km=9.8,
        fc_media=142,
        desnivel_positivo_m=120,
        garmin_activity_id=123456789,
    )
    assert sesion.clase_sesion is None


def test_sesion_realizada_rechaza_descanso():
    with pytest.raises(ValidationError, match="ausencia de actividad"):
        SesionRealizada(
            fecha=date(2026, 10, 13),
            duracion=timedelta(minutes=30),
            distancia_km=5,
            clase_sesion=ClaseSesion.DESCANSO,
        )


def test_sesion_realizada_rechaza_duracion_cero():
    with pytest.raises(ValidationError):
        SesionRealizada(fecha=date(2026, 10, 13), duracion=timedelta(0), distancia_km=0)


def test_sesion_realizada_rechaza_rpe_fuera_de_rango():
    with pytest.raises(ValidationError):
        SesionRealizada(
            fecha=date(2026, 10, 13),
            duracion=timedelta(minutes=40),
            distancia_km=7,
            rpe=11,
        )


def test_sesion_realizada_rechaza_segundos_negativos_en_zona():
    with pytest.raises(ValidationError, match="tiempos negativos"):
        SesionRealizada(
            fecha=date(2026, 10, 13),
            duracion=timedelta(minutes=40),
            distancia_km=7,
            segundos_por_zona={ZonasFC.Z2: -5},
        )


def test_sesion_realizada_rechaza_carga_epoc_negativa():
    with pytest.raises(ValidationError):
        SesionRealizada(
            fecha=date(2026, 10, 13),
            duracion=timedelta(minutes=40),
            distancia_km=7,
            carga_epoc=-1,
        )


def test_sesion_realizada_puede_tener_clase_sin_tipo():
    sesion = SesionRealizada(
        fecha=date(2026, 10, 13),
        duracion=timedelta(minutes=40),
        distancia_km=7,
        clase_sesion=ClaseSesion.ESPECIFICO,
    )
    assert sesion.tipo_sesion is None


def test_sesion_realizada_rechaza_tipo_incoherente_con_clase():
    with pytest.raises(ValidationError):
        SesionRealizada(
            fecha=date(2026, 10, 13),
            duracion=timedelta(minutes=40),
            distancia_km=7,
            clase_sesion=ClaseSesion.FONDO,
            tipo_sesion=TipoSesion.SERIES,
        )


def test_sesion_realizada_rechaza_tipo_sin_clase():
    with pytest.raises(ValidationError, match="requiere clase_sesion"):
        SesionRealizada(
            fecha=date(2026, 10, 13),
            duracion=timedelta(minutes=40),
            distancia_km=7,
            tipo_sesion=TipoSesion.TEMPO,
        )


# ---------- ObjetivosMicrociclo ----------

def test_objetivos_rechaza_conteo_negativo():
    with pytest.raises(ValidationError, match="negativos"):
        ObjetivosMicrociclo(volumen_km=30, sesiones_por_clase={ClaseSesion.ESPECIFICO: -1})


def test_objetivos_por_tiempo_sin_km_es_valido():
    # Uphill Athlete planifica la semana en horas.
    objetivos = ObjetivosMicrociclo(duracion=timedelta(hours=6), desnivel_positivo_m=1500)
    assert objetivos.volumen_km is None


def test_objetivos_necesitan_duracion_o_km():
    with pytest.raises(ValidationError, match="duracion, volumen_km o ambos"):
        ObjetivosMicrociclo(sesiones_por_clase={ClaseSesion.FONDO: 3})


def test_objetivos_rechaza_volumen_negativo():
    with pytest.raises(ValidationError):
        ObjetivosMicrociclo(volumen_km=-5)


# ---------- Microciclo ----------

def test_microciclo_sin_sesiones_es_nivel_2():
    micro = _microciclo(date(2026, 10, 19))
    assert not micro.detallado


def test_microciclo_con_sesiones_es_nivel_1():
    micro = _microciclo(date(2026, 10, 12), sesiones=[_rodaje(date(2026, 10, 14))])
    assert micro.detallado


def test_microciclo_rechaza_sesion_fuera_de_rango():
    with pytest.raises(ValidationError, match="fuera del rango del microciclo"):
        _microciclo(date(2026, 10, 12), sesiones=[_rodaje(date(2026, 10, 25))])


def test_microciclo_rechaza_fecha_fin_antes_de_fecha_inicio():
    with pytest.raises(ValidationError):
        Microciclo(
            fecha_inicio=date(2026, 10, 18),
            fecha_fin=date(2026, 10, 12),
            tipo_microciclo=TipoMicrociclo.CARGA,
            objetivos=_objetivos(),
        )


# ---------- Mesociclo ----------

def test_mesociclo_sin_microciclos_es_esqueleto_valido():
    # Nivel 3: un bloque futuro solo con objetivo y fechas.
    meso = Mesociclo(
        objetivo=ObjetivoMesociclo.FUERZA_Y_ECONOMIA,
        fecha_inicio=date(2026, 11, 2),
        fecha_fin=date(2026, 11, 29),
        volumen_semanal_medio_km=45,
    )
    assert meso.microciclos == []


def test_mesociclo_rechaza_microciclo_fuera_de_rango():
    with pytest.raises(ValidationError, match="fuera del rango del mesociclo"):
        _mesociclo(date(2026, 10, 12), date(2026, 10, 18), [_microciclo(date(2026, 10, 19))])


def test_mesociclo_rechaza_microciclos_solapados():
    with pytest.raises(ValidationError, match="se solapa"):
        _mesociclo(
            date(2026, 10, 12),
            date(2026, 11, 1),
            [_microciclo(date(2026, 10, 12)), _microciclo(date(2026, 10, 15))],
        )


def test_mesociclo_rechaza_microciclos_desordenados():
    with pytest.raises(ValidationError, match="se solapa"):
        _mesociclo(
            date(2026, 10, 12),
            date(2026, 11, 1),
            [_microciclo(date(2026, 10, 19)), _microciclo(date(2026, 10, 12))],
        )


# ---------- Plan ----------

def _plan_construccion(**overrides) -> Plan:
    campos = dict(
        modo=ModoPlan.CONSTRUCCION,
        fecha_inicio=date(2026, 10, 12),
        fecha_objetivo=date(2026, 12, 31),
        mesociclos=[
            _mesociclo(date(2026, 10, 12), date(2026, 11, 8), [_microciclo(date(2026, 10, 12))]),
            _mesociclo(date(2026, 11, 9), date(2026, 12, 31)),
        ],
    )
    campos.update(overrides)
    return Plan(**campos)


def test_plan_construccion_sin_carrera_es_valido():
    plan = _plan_construccion()
    assert plan.carrera is None
    assert plan.version == 1


def test_plan_rechaza_mesociclos_vacio():
    with pytest.raises(ValidationError):
        _plan_construccion(mesociclos=[])


def test_plan_construccion_rechaza_carrera():
    carrera = Carrera(nombre="Trail de prueba", fecha=date(2026, 12, 31), distancia_km=21)
    with pytest.raises(ValidationError, match="construcción no tiene carrera"):
        _plan_construccion(carrera=carrera)


def test_plan_competicion_necesita_carrera():
    with pytest.raises(ValidationError, match="necesita una carrera"):
        _plan_construccion(modo=ModoPlan.COMPETICION)


def test_plan_competicion_fecha_objetivo_es_la_de_la_carrera():
    carrera = Carrera(nombre="Trail de prueba", fecha=date(2026, 12, 20), distancia_km=21)
    with pytest.raises(ValidationError, match="fecha de la carrera"):
        _plan_construccion(modo=ModoPlan.COMPETICION, carrera=carrera)


def test_plan_competicion_valido():
    carrera = Carrera(
        nombre="Trail de prueba", fecha=date(2026, 12, 31), distancia_km=21, desnivel_positivo_m=1200
    )
    plan = _plan_construccion(modo=ModoPlan.COMPETICION, carrera=carrera)
    assert plan.carrera.nombre == "Trail de prueba"


def test_plan_rechaza_mesociclo_fuera_de_rango():
    with pytest.raises(ValidationError, match="fuera del rango del plan"):
        _plan_construccion(mesociclos=[_mesociclo(date(2026, 10, 12), date(2027, 1, 15))])


def test_plan_rechaza_mesociclos_solapados():
    with pytest.raises(ValidationError, match="se solapa"):
        _plan_construccion(
            mesociclos=[
                _mesociclo(date(2026, 10, 12), date(2026, 11, 8)),
                _mesociclo(date(2026, 11, 1), date(2026, 12, 31)),
            ]
        )


def test_plan_rechaza_version_cero():
    with pytest.raises(ValidationError):
        _plan_construccion(version=0)


# ---------- estructura de la sesión (lo que se envía al reloj) ----------

def _series(**cambios) -> SesionPlanificada:
    datos = dict(
        fecha=date(2026, 10, 13),
        clase_sesion=ClaseSesion.ESPECIFICO,
        tipo_sesion=TipoSesion.SERIES,
        zona_fc_objetivo=ZonasFC.Z4,
        duracion_objetivo=timedelta(minutes=50),
        calentamiento=timedelta(minutes=15),
        intervalos=Intervalos(repeticiones=5, trabajo=timedelta(minutes=3), recuperacion=timedelta(minutes=2)),
        vuelta_calma=timedelta(minutes=10),
    )
    datos.update(cambios)
    return SesionPlanificada(**datos)


def test_series_con_estructura_que_suma_la_duracion():
    sesion = _series()  # 15 + 5×(3+2) + 10 = 50 min
    assert sesion.duracion_estructura == timedelta(minutes=50)


def test_series_sin_intervalos_se_rechaza():
    with pytest.raises(ValidationError, match="necesita su estructura"):
        _series(intervalos=None, calentamiento=None, vuelta_calma=None)


def test_estructura_que_no_suma_la_duracion_se_rechaza():
    with pytest.raises(ValidationError, match="suman"):
        _series(duracion_objetivo=timedelta(minutes=60))


def test_continua_necesita_tiempo_para_el_bloque_principal():
    with pytest.raises(ValidationError, match="no dejan tiempo"):
        SesionPlanificada(
            fecha=date(2026, 10, 14),
            clase_sesion=ClaseSesion.FONDO,
            tipo_sesion=TipoSesion.FONDO,
            duracion_objetivo=timedelta(minutes=20),
            calentamiento=timedelta(minutes=10),
            vuelta_calma=timedelta(minutes=10),
        )


def test_descanso_no_lleva_estructura():
    with pytest.raises(ValidationError, match="Descanso"):
        SesionPlanificada(fecha=date(2026, 10, 12), clase_sesion=ClaseSesion.DESCANSO, calentamiento=timedelta(minutes=5))


def test_intervalo_sin_trabajo_se_rechaza():
    with pytest.raises(ValidationError):
        Intervalos(repeticiones=4, trabajo=timedelta(0))


def test_una_sola_repeticion_no_son_intervalos():
    # Una sesión continua se expresa con calentamiento + bloque + vuelta a la
    # calma, no como "1 × (25' + 0')".
    with pytest.raises(ValidationError):
        Intervalos(repeticiones=1, trabajo=timedelta(minutes=25))



def test_sprints_en_cuesta_y_aceleraciones_son_rodajes_con_intervalos():
    from datetime import date

    from core.training import ClaseSesion, SesionPlanificada, TipoSesion

    sprints = SesionPlanificada(
        fecha=date(2026, 10, 20), clase_sesion=ClaseSesion.FONDO, tipo_sesion=TipoSesion.SPRINTS_CUESTA,
        duracion_objetivo=timedelta(minutes=57, seconds=20), calentamiento=timedelta(minutes=20),
        vuelta_calma=timedelta(minutes=20),
        intervalos=Intervalos(repeticiones=8, trabajo=timedelta(seconds=10), recuperacion=timedelta(minutes=2)),
    )
    assert sprints.intervalos.repeticiones == 8
    with pytest.raises(ValidationError, match="necesita su estructura"):
        SesionPlanificada(
            fecha=date(2026, 10, 20), clase_sesion=ClaseSesion.FONDO, tipo_sesion=TipoSesion.ACELERACIONES,
            duracion_objetivo=timedelta(minutes=50),
        )
