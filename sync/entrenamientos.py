# Traducción determinista SesionPlanificada → entrenamiento de Garmin (JSON
# que acepta la tool upload_workout de garmin-mcp). Función pura: sin red,
# sin LLM.
#
# Lo que el reloj puede estructurar va en pasos (warmup, bloque principal o
# series, cooldown) con su objetivo de zona de FC. Lo que no puede (desnivel,
# terreno, indicaciones de la sesión) va en las notas del entrenamiento
# (`description`), que se ven en Garmin Connect y en el reloj.
#
# Textos con la jerga habitual del running (Warmup, Cooldown, Rec, Umbral,
# Tempo...) y cortos: en la pantalla del reloj caben pocas palabras.

from typing import Any, Optional

from core.training import ClaseSesion, SesionPlanificada, TipoSesion, ZonasFC

PREFIJO_NOMBRE = "PB"  # identifica en la biblioteca de Garmin lo que crea PB_coach

_DEPORTE = {"sportTypeId": 1, "sportTypeKey": "running"}
_PASO = {
    "calentamiento": {"stepTypeId": 1, "stepTypeKey": "warmup"},
    "vuelta_calma": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
    "trabajo": {"stepTypeId": 3, "stepTypeKey": "interval"},
    "recuperacion": {"stepTypeId": 4, "stepTypeKey": "recovery"},
}
# Etiquetas de cada paso, como se dicen al entrenar.
_ETIQUETA_PASO = {"calentamiento": "Warmup", "vuelta_calma": "Cooldown", "recuperacion": "Rec"}
_ETIQUETA_TIPO = {
    TipoSesion.SERIES: "Series",
    TipoSesion.TEMPO: "Tempo",
    TipoSesion.UMBRAL: "Umbral",
    TipoSesion.BASE: "Base",
    TipoSesion.FONDO: "Fondo",
    TipoSesion.FUERZA: "Fuerza",
    TipoSesion.RECUPERACION: "Regenerativo",
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


def etiqueta_sesion(sesion: SesionPlanificada) -> str:
    if sesion.tipo_sesion is not None:
        return _ETIQUETA_TIPO[sesion.tipo_sesion]
    return sesion.clase_sesion.value


def nombre_entrenamiento(sesion: SesionPlanificada) -> str:
    return f"{PREFIJO_NOMBRE} {sesion.fecha:%d/%m} {etiqueta_sesion(sesion)}"


def notas(sesion: SesionPlanificada, origen: str) -> str:
    """Notas cortas: la indicación de la sesión, una línea con terreno, D+ y
    km orientativos, y el origen. Ej.:

        Sube andando las rampas; baja suelto.
        Sendero técnico · D+ 450 m · ~9 km
        PB_coach p3 v5
    """
    datos = []
    if sesion.terreno is not None:
        datos.append(sesion.terreno.value)
    if sesion.desnivel_positivo_objetivo_m:
        datos.append(f"D+ {sesion.desnivel_positivo_objetivo_m:.0f} m")
    if sesion.distancia_objetivo_km and sesion.duracion_objetivo:
        datos.append(f"~{sesion.distancia_objetivo_km:g} km")

    lineas = [sesion.descripcion] if sesion.descripcion else []
    if datos:
        lineas.append(" · ".join(datos))
    lineas.append(origen)
    return "\n".join(lineas)


def sesion_a_entrenamiento(sesion: SesionPlanificada, origen: str = "PB_coach") -> Optional[dict[str, Any]]:
    """JSON de entrenamiento de Garmin para una sesión, o None si es descanso.

    `origen` se añade al final de las notas (p. ej. "PB_coach p3 v5")
    para saber de qué versión del plan sale cada entrenamiento.
    """
    if sesion.clase_sesion == ClaseSesion.DESCANSO:
        return None

    pasos: list[dict[str, Any]] = []

    def siguiente() -> int:
        return len(pasos) + 1

    trabajo = etiqueta_sesion(sesion)

    if sesion.calentamiento:
        pasos.append(_paso(siguiente(), "calentamiento", segundos=sesion.calentamiento.total_seconds(),
                           descripcion=_ETIQUETA_PASO["calentamiento"]))

    if sesion.intervalos is not None:
        i = sesion.intervalos
        series = [_paso(1, "trabajo", segundos=i.trabajo.total_seconds(), zona=sesion.zona_fc_objetivo, descripcion=trabajo)]
        if i.recuperacion.total_seconds() > 0:
            series.append(_paso(2, "recuperacion", segundos=i.recuperacion.total_seconds(), zona=i.zona_fc_recuperacion,
                                descripcion=_ETIQUETA_PASO["recuperacion"]))
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
        pasos.append(_paso(siguiente(), "trabajo", segundos=principal.total_seconds(), zona=sesion.zona_fc_objetivo,
                           descripcion=trabajo))
    else:
        pasos.append(_paso(siguiente(), "trabajo", metros=sesion.distancia_objetivo_km * 1000, zona=sesion.zona_fc_objetivo,
                           descripcion=trabajo))

    if sesion.vuelta_calma:
        pasos.append(_paso(siguiente(), "vuelta_calma", segundos=sesion.vuelta_calma.total_seconds(),
                           descripcion=_ETIQUETA_PASO["vuelta_calma"]))

    return {
        "workoutName": nombre_entrenamiento(sesion),
        "description": notas(sesion, origen),
        "sportType": _DEPORTE,
        "workoutSegments": [{"segmentOrder": 1, "sportType": _DEPORTE, "workoutSteps": pasos}],
    }
