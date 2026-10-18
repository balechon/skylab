# Traducción entre los modelos de SKYLAB y las filas de las bases de Notion.
# Funciones puras: sin red, sin estado. Los nombres de las columnas están
# aquí y solo aquí.
#
# Cada fila que escribe SKYLAB lleva una Clave estable (el lunes de la
# semana, o la fecha y el orden de la sesión): así se actualiza la misma fila
# en cada versión del plan y nunca se duplica. Las columnas del atleta
# (Observaciones, Comentario, Evaluar, Recalcular) nunca se sobrescriben.

from datetime import date, timedelta
from typing import Any, Optional

from core.athlete import FichaAtleta
from core.etiquetas import etiqueta_sesion
from core.training import (
    ClaseSesion,
    Mesociclo,
    Microciclo,
    RangoFC,
    SesionPlanificada,
    SesionRealizada,
    ZonasFC,
)
from notion import propiedades as p

_DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

# ---------- claves ----------


def clave_semana(micro: Microciclo) -> str:
    return micro.fecha_inicio.isoformat()


def clave_sesion(fecha: date, orden: int) -> str:
    return f"{fecha.isoformat()}#{orden}"


def clave_actividad(garmin_activity_id: int) -> str:
    return f"garmin:{garmin_activity_id}"


def es_clave_de_sesion(clave: Optional[str]) -> bool:
    return bool(clave) and "#" in clave


def sin_guiones(page_id: str) -> str:
    return page_id.replace("-", "")


# ---------- textos ----------


def nombre_semana(numero: int, micro: Microciclo) -> str:
    inicio, fin = micro.fecha_inicio, micro.fecha_fin
    if inicio.month == fin.month:
        rango = f"{inicio.day}–{fin.day} {_MESES[fin.month - 1]}"
    else:
        rango = f"{inicio.day} {_MESES[inicio.month - 1]}–{fin.day} {_MESES[fin.month - 1]}"
    return f"S{numero} · {rango}"


def nombre_sesion(fecha: date, etiqueta: str) -> str:
    return f"{_DIAS[fecha.weekday()]} {fecha:%d/%m} · {etiqueta}"


def _duracion(td: timedelta) -> str:
    segundos = int(td.total_seconds())
    minutos, resto = divmod(segundos, 60)
    if resto and minutos:
        return f"{minutos}'{resto:02d}\""
    if resto:
        return f'{resto}"'
    return f"{minutos}'"


def estructura(sesion: SesionPlanificada) -> Optional[str]:
    """La sesión en una línea, como se lee en el reloj."""
    if sesion.duracion_objetivo is None:
        return None
    partes = []
    if sesion.calentamiento:
        partes.append(f"Warmup {_duracion(sesion.calentamiento)}")
    zona = sesion.zona_fc_objetivo.value if sesion.zona_fc_objetivo else ""
    if sesion.intervalos is not None:
        i = sesion.intervalos
        rec = f" + {_duracion(i.recuperacion)} Rec" if i.recuperacion.total_seconds() else ""
        partes.append(f"{i.repeticiones} × ({_duracion(i.trabajo)} {etiqueta_sesion(sesion)}{rec})")
    else:
        principal = sesion.duracion_objetivo - sesion.duracion_estructura
        partes.append(f"{_duracion(principal)} {zona}".strip())
    if sesion.vuelta_calma:
        partes.append(f"Cooldown {_duracion(sesion.vuelta_calma)}")
    return " · ".join(partes)


def fc_objetivo(zona: Optional[ZonasFC], rangos: dict[ZonasFC, RangoFC]) -> Optional[str]:
    rango = rangos.get(zona) if zona else None
    if rango is None:
        return None
    return f"<{rango.maximo}" if rango.minimo is None else f"{rango.minimo}-{rango.maximo}"


# ---------- SKYLAB → Notion ----------


def propiedades_semana(numero: int, micro: Microciclo, meso: Mesociclo, version: int) -> dict[str, Any]:
    objetivos = micro.objetivos
    horas = round(objetivos.duracion.total_seconds() / 3600, 2) if objetivos.duracion else None
    return {
        "Semana": p.titulo(nombre_semana(numero, micro)),
        "Clave": p.texto(clave_semana(micro)),
        "Inicio": p.fecha(micro.fecha_inicio),
        "Bloque": p.seleccion(meso.objetivo.value),
        "Tipo": p.seleccion(micro.tipo_microciclo.value),
        "Nivel": p.seleccion("Sesiones concretas" if micro.detallado else "Objetivos"),
        "Horas objetivo": p.numero(horas),
        "Km objetivo": p.numero(objetivos.volumen_km),
        "D+ objetivo (m)": p.numero(objetivos.desnivel_positivo_m),
        "Versión del plan": p.numero(version),
    }


def sesiones_con_orden(micro: Microciclo) -> list[tuple[int, SesionPlanificada]]:
    """Las sesiones con carga de una semana, con su orden dentro del día."""
    resultado = []
    por_dia: dict[date, int] = {}
    for sesion in sorted(micro.sesiones, key=lambda s: s.fecha):
        if sesion.clase_sesion == ClaseSesion.DESCANSO:
            continue
        por_dia[sesion.fecha] = por_dia.get(sesion.fecha, 0) + 1
        resultado.append((por_dia[sesion.fecha], sesion))
    return resultado


def propiedades_sesion(
    sesion: SesionPlanificada, orden: int, rangos: dict[ZonasFC, RangoFC], semana_page_id: Optional[str]
) -> dict[str, Any]:
    return {
        "Sesión": p.titulo(nombre_sesion(sesion.fecha, etiqueta_sesion(sesion))),
        "Clave": p.texto(clave_sesion(sesion.fecha, orden)),
        "Fecha": p.fecha(sesion.fecha),
        "Semana": p.relacion([semana_page_id] if semana_page_id else []),
        "Clase": p.seleccion(sesion.clase_sesion.value),
        "Tipo": p.seleccion(sesion.tipo_sesion.value if sesion.tipo_sesion else None),
        "Duración (min)": p.numero(round(sesion.duracion_objetivo.total_seconds() / 60) if sesion.duracion_objetivo else None),
        "Zona": p.seleccion(sesion.zona_fc_objetivo.value if sesion.zona_fc_objetivo else None),
        "FC objetivo": p.texto(fc_objetivo(sesion.zona_fc_objetivo, rangos)),
        "Terreno": p.seleccion(sesion.terreno.value if sesion.terreno else None),
        "D+ (m)": p.numero(sesion.desnivel_positivo_objetivo_m),
        "Estructura": p.texto(estructura(sesion)),
        "Notas del reloj": p.texto(sesion.descripcion),
        "Vigente": p.casilla(True),
    }


def propiedades_actividad_extra(actividad: SesionRealizada, semana_page_id: Optional[str]) -> dict[str, Any]:
    """Una actividad de Garmin que no estaba en el plan: su propia fila, para
    que el atleta también pueda comentarla."""
    return {
        "Sesión": p.titulo(nombre_sesion(actividad.fecha, "Actividad extra")),
        "Clave": p.texto(clave_actividad(actividad.garmin_activity_id)),
        "Fecha": p.fecha(actividad.fecha),
        "Semana": p.relacion([semana_page_id] if semana_page_id else []),
        "Vigente": p.casilla(False),
    }


def propiedades_hecho(actividades: list[SesionRealizada]) -> dict[str, Any]:
    """Lo realizado (de Garmin) en las columnas "Hecho". Varias actividades
    el mismo día se suman; la FC media se pondera por la duración."""
    segundos = sum(a.duracion.total_seconds() for a in actividades)
    con_fc = [a for a in actividades if a.fc_media]
    segundos_fc = sum(a.duracion.total_seconds() for a in con_fc)
    fc = round(sum(a.fc_media * a.duracion.total_seconds() for a in con_fc) / segundos_fc) if segundos_fc else None
    dmas = sum(a.desnivel_positivo_m or 0 for a in actividades)
    ultima = actividades[-1]
    return {
        "Hecho: duración (min)": p.numero(round(segundos / 60)),
        "Hecho: km": p.numero(round(sum(a.distancia_km for a in actividades), 2)),
        "Hecho: FC media": p.numero(fc),
        "Hecho: D+ (m)": p.numero(round(dmas) if dmas else None),
        "RPE": p.numero(ultima.rpe),
        "Sensación": p.seleccion(ultima.sensaciones),
    }


def propiedades_feedback(feedback: dict[str, Any], mensaje: str) -> dict[str, Any]:
    consejos = "\n".join(
        f"• {c['texto']}" + (f" ({c['regla_id']})" if c.get("regla_id") else "") for c in feedback.get("consejos", [])
    )
    return {
        "Qué pasó": p.texto(feedback.get("lo_que_paso")),
        "Por qué cambia": p.texto(feedback.get("por_que_cambia")),
        "Consejos": p.texto(consejos or None),
        "Estado": p.seleccion("Evaluada"),
        "Mensaje SKYLAB": p.texto(mensaje),
    }


def propiedades_fin_de_peticion(mensaje: str) -> dict[str, Any]:
    """Desmarca Evaluar y Recalcular y deja el aviso del resultado."""
    return {"Evaluar": p.casilla(False), "Recalcular": p.casilla(False), "Mensaje SKYLAB": p.texto(mensaje)}


# ---------- Notion → SKYLAB ----------


def ficha_desde_fila(fila: dict[str, Any]) -> FichaAtleta:
    """La ficha del atleta a partir de su fila de Notion. Lanza
    pydantic.ValidationError si algún dato no es válido."""
    maximo_largo = p.leer(fila, "Máx día largo (min)")
    disponibilidad = None
    if p.leer(fila, "Máx por día (min)") is not None:
        disponibilidad = {
            "duracion_max_dia": timedelta(minutes=p.leer(fila, "Máx por día (min)")),
            "dias_sin_entrenar": p.leer(fila, "Días sin entrenar") or [],
            "dias_largos": p.leer(fila, "Días largos") or [],
            "dias_largos_por_semana": int(p.leer(fila, "Días largos por semana") or 0),
            "duracion_max_dia_largo": timedelta(minutes=maximo_largo) if maximo_largo else None,
        }
    def entero(nombre: str) -> Optional[int]:
        v = p.leer(fila, nombre)
        return int(v) if v is not None else None

    return FichaAtleta.model_validate(
        {
            "edad": entero("Edad"),
            "categoria": p.leer(fila, "Categoría"),
            "umbrales": {
                "fc_aerobico": entero("AeT (ppm)"),
                "metodo_aerobico": p.leer(fila, "Método AeT"),
                "fc_lactato": entero("LT (ppm)"),
                "fc_maxima": entero("FC máx (ppm)"),
                "fc_reposo": entero("FC reposo (ppm)"),
                "fecha": p.leer(fila, "Fecha umbrales"),
            },
            "disponibilidad": disponibilidad,
            "lesiones": p.leer(fila, "Lesiones"),
            "notas": p.leer(fila, "Notas"),
        }
    )


def comentarios_para_ajuste(
    semana_cerrada: date, filas_sesiones: list[dict[str, Any]], observaciones: list[str]
) -> Optional[dict[str, Any]]:
    """Los comentarios del atleta para el ajuste semanal: los de las sesiones
    de la semana cerrada y sus observaciones para lo que viene."""
    fin = semana_cerrada + timedelta(days=6)
    por_sesion = []
    for fila in filas_sesiones:
        fecha, comentario = p.leer(fila, "Fecha"), p.leer(fila, "Comentario")
        if fecha and comentario and semana_cerrada <= fecha <= fin:
            por_sesion.append({"fecha": fecha.isoformat(), "texto": comentario[:500]})
    general = "\n".join(dict.fromkeys(o.strip() for o in observaciones if o and o.strip())) or None
    if not por_sesion and not general:
        return None
    return {"general": general[:1000] if general else None, "por_sesion": sorted(por_sesion, key=lambda c: c["fecha"])}
