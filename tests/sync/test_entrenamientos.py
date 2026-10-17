# Traducción SesionPlanificada → JSON de entrenamiento de Garmin, sin red.

from datetime import date, timedelta

from core.training import ClaseSesion, Intervalos, SesionPlanificada, Terreno, TipoSesion, ZonasFC
from sync.entrenamientos import sesion_a_entrenamiento

MARTES = date(2026, 10, 20)


def _pasos(entrenamiento):
    return entrenamiento["workoutSegments"][0]["workoutSteps"]


def test_descanso_no_genera_entrenamiento():
    assert sesion_a_entrenamiento(SesionPlanificada(fecha=MARTES, clase_sesion=ClaseSesion.DESCANSO)) is None


def test_series_por_tiempo_con_calentamiento_y_vuelta_a_la_calma():
    sesion = SesionPlanificada(
        fecha=MARTES,
        clase_sesion=ClaseSesion.ESPECIFICO,
        tipo_sesion=TipoSesion.SERIES,
        terreno=Terreno.PISTA,
        zona_fc_objetivo=ZonasFC.Z4,
        duracion_objetivo=timedelta(minutes=50),
        calentamiento=timedelta(minutes=15),
        intervalos=Intervalos(
            repeticiones=5, trabajo=timedelta(minutes=3), recuperacion=timedelta(minutes=2), zona_fc_recuperacion=ZonasFC.Z1
        ),
        vuelta_calma=timedelta(minutes=10),
        descripcion="Series cortas, la última más rápida.",
    )
    e = sesion_a_entrenamiento(sesion, origen="PB_coach · plan 3 v5")

    assert e["workoutName"] == "PB 20/10 Series"
    assert e["sportType"]["sportTypeKey"] == "running"
    calentamiento, series, vuelta = _pasos(e)
    assert (calentamiento["stepType"]["stepTypeKey"], calentamiento["endConditionValue"]) == ("warmup", 900.0)
    assert series["type"] == "RepeatGroupDTO" and series["numberOfIterations"] == 5
    assert series["endCondition"] == {"conditionTypeId": 7, "conditionTypeKey": "iterations"}
    trabajo, recuperacion = series["workoutSteps"]
    assert (trabajo["endConditionValue"], trabajo["zoneNumber"]) == (180.0, 4)
    assert (recuperacion["endConditionValue"], recuperacion["zoneNumber"]) == (120.0, 1)
    assert "targetValueOne" not in trabajo  # la zona va en zoneNumber, nunca en targetValueOne
    assert (vuelta["stepType"]["stepTypeKey"], vuelta["endConditionValue"]) == ("cooldown", 600.0)
    assert e["description"] == "Series cortas, la última más rápida.\nTerreno: Pista\nPB_coach · plan 3 v5"


def test_fondo_de_trail_lleva_desnivel_y_terreno_en_las_notas():
    sesion = SesionPlanificada(
        fecha=date(2026, 10, 24),
        clase_sesion=ClaseSesion.FONDO,
        tipo_sesion=TipoSesion.FONDO,
        terreno=Terreno.SENDERO_TECNICO,
        zona_fc_objetivo=ZonasFC.Z2,
        duracion_objetivo=timedelta(minutes=80),
        distancia_objetivo_km=9,
        desnivel_positivo_objetivo_m=450,
        calentamiento=timedelta(minutes=10),
        descripcion="Sube andando las rampas fuertes; baja suelto.",
    )
    e = sesion_a_entrenamiento(sesion)

    calentamiento, principal = _pasos(e)
    assert principal["endConditionValue"] == 70 * 60.0  # 80' - 10' de calentamiento
    assert principal["zoneNumber"] == 2
    assert e["description"].splitlines() == [
        "Sube andando las rampas fuertes; baja suelto.",
        "Terreno: Sendero técnico",
        "Desnivel +: 450 m",
        "Distancia orientativa: 9 km",
        "PB_coach",
    ]


def test_sesion_solo_por_distancia_usa_un_paso_de_distancia():
    sesion = SesionPlanificada(
        fecha=MARTES,
        clase_sesion=ClaseSesion.RECUPERACION,
        tipo_sesion=TipoSesion.RECUPERACION,
        distancia_objetivo_km=5,
    )
    (principal,) = _pasos(sesion_a_entrenamiento(sesion))
    assert principal["endCondition"]["conditionTypeKey"] == "distance"
    assert principal["endConditionValue"] == 5000.0
    assert principal["targetType"]["workoutTargetTypeKey"] == "no.target"


def test_series_sin_recuperacion_solo_tiene_el_paso_de_trabajo():
    sesion = SesionPlanificada(
        fecha=MARTES,
        clase_sesion=ClaseSesion.ESPECIFICO,
        tipo_sesion=TipoSesion.SERIES,
        distancia_objetivo_km=6,
        intervalos=Intervalos(repeticiones=8, trabajo=timedelta(seconds=30)),
    )
    (series,) = _pasos(sesion_a_entrenamiento(sesion))
    assert len(series["workoutSteps"]) == 1
