# Cálculo de volumen a partir de sesiones realizadas.
#
# Funciones puras: reciben datos de domain/ y devuelven datos nuevos, sin IO
# ni LLM. Mismo input → mismo output.
#
# En trail los kilómetros solos engañan (10 km con 800 m D+ no equivalen a
# 10 km en llano), así que el volumen se resume en tiempo, distancia y
# desnivel a la vez.
#
# Carga: la principal es la de Garmin (EPOC); el respaldo es sRPE
# (rpe x minutos). Están en escalas distintas, así que nunca se suman entre
# sí: se llevan como dos series paralelas y al comparar periodos se elige la
# que esté completa en ambos (ver comparar_carga).

from collections import Counter
from datetime import date, timedelta
from enum import Enum
from typing import Iterable, Optional

from pydantic import BaseModel

from pb_coach.domain.training import ClaseSesion, SesionRealizada, ZonasFC


class ResumenPeriodo(BaseModel):
    """Volumen realizado entre dos fechas (ambas incluidas). Es lo que ve el
    LLM en lugar de las sesiones crudas."""

    fecha_inicio: date
    fecha_fin: date
    numero_sesiones: int
    distancia_km: float
    duracion: timedelta
    desnivel_positivo_m: float
    sesiones_por_clase: dict[ClaseSesion, int]
    duracion_por_zona: dict[ZonasFC, timedelta]
    sesiones_sin_clasificar: int

    carga_epoc: float
    sesiones_con_epoc: int
    carga_srpe: float
    sesiones_con_rpe: int


class FuenteCarga(str, Enum):
    EPOC = "epoc"
    SRPE = "srpe"


class ComparacionCarga(BaseModel):
    """Carga de dos periodos medida con la misma fuente."""

    fuente: FuenteCarga
    anterior: float
    actual: float
    variacion_pct: Optional[float]


def carga_srpe(sesion: SesionRealizada) -> Optional[float]:
    """sRPE de una sesión: rpe x minutos. None si no hay RPE."""
    if sesion.rpe is None:
        return None
    return round(sesion.rpe * sesion.duracion.total_seconds() / 60, 1)


def inicio_de_semana(fecha: date) -> date:
    """Lunes de la semana de `fecha`."""
    return fecha - timedelta(days=fecha.weekday())


def resumir_periodo(
    sesiones: Iterable[SesionRealizada], fecha_inicio: date, fecha_fin: date
) -> ResumenPeriodo:
    """Agrega las sesiones que caen dentro de [fecha_inicio, fecha_fin].

    Las sesiones fuera del rango se ignoran. Un periodo sin sesiones devuelve
    un resumen con todo a cero, no None: una semana sin entrenar es un dato.
    """
    if fecha_fin < fecha_inicio:
        raise ValueError("fecha_fin debe ser posterior (o igual) a fecha_inicio")

    dentro = [s for s in sesiones if fecha_inicio <= s.fecha <= fecha_fin]

    duracion_por_zona: dict[ZonasFC, timedelta] = {}
    for s in dentro:
        for zona, segundos in s.segundos_por_zona.items():
            duracion_por_zona[zona] = duracion_por_zona.get(zona, timedelta(0)) + timedelta(seconds=segundos)

    return ResumenPeriodo(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        numero_sesiones=len(dentro),
        distancia_km=round(sum(s.distancia_km for s in dentro), 2),
        duracion=sum((s.duracion for s in dentro), timedelta(0)),
        desnivel_positivo_m=sum(s.desnivel_positivo_m or 0 for s in dentro),
        sesiones_por_clase=dict(Counter(s.clase_sesion for s in dentro if s.clase_sesion is not None)),
        duracion_por_zona=duracion_por_zona,
        sesiones_sin_clasificar=sum(1 for s in dentro if s.clase_sesion is None),
        carga_epoc=round(sum(s.carga_epoc for s in dentro if s.carga_epoc is not None), 1),
        sesiones_con_epoc=sum(1 for s in dentro if s.carga_epoc is not None),
        carga_srpe=round(sum(c for s in dentro if (c := carga_srpe(s)) is not None), 1),
        sesiones_con_rpe=sum(1 for s in dentro if s.rpe is not None),
    )


def resumir_semanas(
    sesiones: Iterable[SesionRealizada], desde: date, hasta: date
) -> list[ResumenPeriodo]:
    """Un resumen por semana (lunes a domingo) que toque [desde, hasta], en
    orden cronológico, incluidas las semanas sin ninguna sesión."""
    if hasta < desde:
        raise ValueError("hasta debe ser posterior (o igual) a desde")

    sesiones = list(sesiones)
    resumenes = []
    lunes = inicio_de_semana(desde)
    while lunes <= hasta:
        resumenes.append(resumir_periodo(sesiones, lunes, lunes + timedelta(days=6)))
        lunes += timedelta(days=7)
    return resumenes


def variacion_pct(anterior: float, actual: float) -> Optional[float]:
    """Cambio porcentual de `anterior` a `actual`, redondeado a 1 decimal.

    Devuelve None si `anterior` es 0: no hay base contra la que medir, y
    inventar un número (0% o infinito) escondería ese hecho.
    """
    if anterior == 0:
        return None
    return round((actual - anterior) / anterior * 100, 1)


def comparar_carga(anterior: ResumenPeriodo, actual: ResumenPeriodo) -> Optional[ComparacionCarga]:
    """Compara la carga de dos periodos con una sola fuente: EPOC si todas
    las sesiones de ambos periodos la tienen; si no, sRPE con la misma
    condición. Si ninguna fuente está completa en ambos, devuelve None:
    comparar con datos parciales daría un número engañoso.
    """
    def completa(resumen: ResumenPeriodo, con_dato: int) -> bool:
        return con_dato == resumen.numero_sesiones

    if completa(anterior, anterior.sesiones_con_epoc) and completa(actual, actual.sesiones_con_epoc):
        fuente, valor_anterior, valor_actual = FuenteCarga.EPOC, anterior.carga_epoc, actual.carga_epoc
    elif completa(anterior, anterior.sesiones_con_rpe) and completa(actual, actual.sesiones_con_rpe):
        fuente, valor_anterior, valor_actual = FuenteCarga.SRPE, anterior.carga_srpe, actual.carga_srpe
    else:
        return None

    return ComparacionCarga(
        fuente=fuente,
        anterior=valor_anterior,
        actual=valor_actual,
        variacion_pct=variacion_pct(valor_anterior, valor_actual),
    )
