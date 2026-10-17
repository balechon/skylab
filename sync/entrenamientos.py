# Traducción determinista SesionPlanificada → entrenamiento de Garmin (JSON
# que acepta la tool upload_workout de garmin-mcp). Función pura: sin red,
# sin LLM.
#
# Lo que el reloj puede estructurar va en pasos (calentamiento, bloque
# principal o series, vuelta a la calma) con su objetivo de zona de FC. Lo
# que no puede (desnivel, terreno, indicaciones de la sesión) va en las
# notas del entrenamiento (`description`), que se ven en Garmin Connect y en
# el reloj.

from typing import Any, Optional

from core.training import ClaseSesion, SesionPlanificada, ZonasFC

PREFIJO_NOMBRE = "PB"  # identifica en la biblioteca de Garmin lo que crea PB_coach

_DEPORTE = {"sportTypeId": 1, "sportTypeKey": "running"}
_PASO = {
    "calentamiento": {"stepTypeId": 1, "stepTypeKey": "warmup"},
    "vuelta_calma": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
    "trabajo": {"stepTypeId": 3, "stepTypeKey": "interval"},
    "recuperacion": {"stepTypeId": 4, "stepTypeKey": "recovery"},
}
_SIN_OBJETIVO = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
_ZONA_FC = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}


def _paso(
    orden: int,
    tipo: str,
    segundos: Optional[float] = None,
    metros: Optional[float] = None,
    zona: Optional[ZonasFC] = None,
    descripcion: Optional[str] = None,
) -> dict[str, Any]:
    paso: dict[str, Any] = {"type": "ExecutableStepDTO", "stepOrder": orden, "stepType": _PASO[tipo]}
    if descripcion:
        paso["description"] = descripcion
    if segundos is not None:
        paso["endCondition"] = {"conditionTypeId": 2, "conditionTypeKey": "time"}
        paso["endConditionValue"] = float(round(segundos))
    else:
        paso["endCondition"] = {"conditionTypeId": 3, "conditionTypeKey": "distance"}
        paso["endConditionValue"] = float(round(metros))
    if zona is None:
        paso["targetType"] = _SIN_OBJETIVO
    else:
        # Zona con nombre: zoneNumber, nunca en targetValueOne (ver la doc de upload_workout).
        paso["targetType"] = _ZONA_FC
        paso["zoneNumber"] = int(zona.value[1])
    return paso


def nombre_entrenamiento(sesion: SesionPlanificada) -> str:
    detalle = sesion.tipo_sesion.value if sesion.tipo_sesion else sesion.clase_sesion.value
    return f"{PREFIJO_NOMBRE} {sesion.fecha:%d/%m} {detalle}"


def notas(sesion: SesionPlanificada, origen: str) -> str:
    lineas = []
    if sesion.descripcion:
        lineas.append(sesion.descripcion)
    if sesion.terreno is not None:
        lineas.append(f"Terreno: {sesion.terreno.value}")
    if sesion.desnivel_positivo_objetivo_m:
        lineas.append(f"Desnivel +: {sesion.desnivel_positivo_objetivo_m:.0f} m")
    if sesion.distancia_objetivo_km and sesion.duracion_objetivo:
        lineas.append(f"Distancia orientativa: {sesion.distancia_objetivo_km:g} km")
    lineas.append(origen)
    return "\n".join(lineas)


def sesion_a_entrenamiento(sesion: SesionPlanificada, origen: str = "PB_coach") -> Optional[dict[str, Any]]:
    """JSON de entrenamiento de Garmin para una sesión, o None si es descanso.

    `origen` se añade al final de las notas (p. ej. "PB_coach · plan 3 v5")
    para saber de qué versión del plan sale cada entrenamiento.
    """
    if sesion.clase_sesion == ClaseSesion.DESCANSO:
        return None

    pasos: list[dict[str, Any]] = []

    def siguiente() -> int:
        return len(pasos) + 1

    if sesion.calentamiento:
        pasos.append(_paso(siguiente(), "calentamiento", segundos=sesion.calentamiento.total_seconds()))

    if sesion.intervalos is not None:
        i = sesion.intervalos
        series = [_paso(1, "trabajo", segundos=i.trabajo.total_seconds(), zona=sesion.zona_fc_objetivo)]
        if i.recuperacion.total_seconds() > 0:
            series.append(_paso(2, "recuperacion", segundos=i.recuperacion.total_seconds(), zona=i.zona_fc_recuperacion))
        pasos.append(
            {
                "type": "RepeatGroupDTO",
                "stepOrder": siguiente(),
                "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
                "numberOfIterations": i.repeticiones,
                # Sin conditionTypeId 7 Garmin corrompe en silencio el número de repeticiones.
                "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
                "endConditionValue": float(i.repeticiones),
                "workoutSteps": series,
            }
        )
    elif sesion.duracion_objetivo is not None:
        principal = sesion.duracion_objetivo - sesion.duracion_estructura
        pasos.append(_paso(siguiente(), "trabajo", segundos=principal.total_seconds(), zona=sesion.zona_fc_objetivo))
    else:
        pasos.append(_paso(siguiente(), "trabajo", metros=sesion.distancia_objetivo_km * 1000, zona=sesion.zona_fc_objetivo))

    if sesion.vuelta_calma:
        pasos.append(_paso(siguiente(), "vuelta_calma", segundos=sesion.vuelta_calma.total_seconds()))

    return {
        "workoutName": nombre_entrenamiento(sesion),
        "description": notas(sesion, origen),
        "sportType": _DEPORTE,
        "workoutSegments": [{"segmentOrder": 1, "sportType": _DEPORTE, "workoutSteps": pasos}],
    }
