from datetime import date, timedelta

import pytest

from core.training import ClaseSesion, SesionRealizada, TipoSesion, ZonasFC
from core.calculator import (
    FuenteCarga,
    carga_srpe,
    comparar_carga,
    inicio_de_semana,
    resumir_periodo,
    resumir_semanas,
    variacion_pct,
)

# Semana del lunes 12 al domingo 18 de octubre de 2026.
LUNES = date(2026, 10, 12)
DOMINGO = date(2026, 10, 18)


def _sesion(fecha, minutos, km, d_mas=None, clase=None, tipo=None, zonas=None, epoc=None, rpe=None) -> SesionRealizada:
    return SesionRealizada(
        fecha=fecha,
        duracion=timedelta(minutes=minutos),
        distancia_km=km,
        desnivel_positivo_m=d_mas,
        clase_sesion=clase,
        tipo_sesion=tipo,
        segundos_por_zona=zonas or {},
        carga_epoc=epoc,
        rpe=rpe,
    )


SEMANA = [
    _sesion(date(2026, 10, 13), 50, 8.0, 40, ClaseSesion.ESPECIFICO, TipoSesion.SERIES,
            {ZonasFC.Z2: 900, ZonasFC.Z4: 2100}),
    _sesion(date(2026, 10, 15), 60, 10.5, 150, ClaseSesion.FONDO, TipoSesion.BASE,
            {ZonasFC.Z2: 3000, ZonasFC.Z3: 600}),
    # Trail largo: el pulso sube en las cuestas aunque sea Fondo.
    _sesion(date(2026, 10, 18), 150, 18.25, 900, ClaseSesion.FONDO, TipoSesion.FONDO,
            {ZonasFC.Z2: 4200, ZonasFC.Z3: 3000, ZonasFC.Z4: 1800}),
    _sesion(date(2026, 10, 16), 30, 5.0),  # sin clasificar, sin D+, sin zonas
]


# ---------- inicio_de_semana ----------

@pytest.mark.parametrize("fecha", [LUNES, date(2026, 10, 15), DOMINGO])
def test_inicio_de_semana_es_el_lunes(fecha):
    assert inicio_de_semana(fecha) == LUNES


# ---------- resumir_periodo ----------

def test_resumen_suma_distancia_tiempo_y_desnivel():
    resumen = resumir_periodo(SEMANA, LUNES, DOMINGO)
    assert resumen.numero_sesiones == 4
    assert resumen.distancia_km == 41.75          # 8 + 10.5 + 18.25 + 5
    assert resumen.duracion == timedelta(minutes=290)  # 50 + 60 + 150 + 30
    assert resumen.desnivel_positivo_m == 1090    # 40 + 150 + 900 + 0


def test_resumen_cuenta_por_clase_y_separa_sin_clasificar():
    resumen = resumir_periodo(SEMANA, LUNES, DOMINGO)
    assert resumen.sesiones_por_clase == {ClaseSesion.FONDO: 2, ClaseSesion.ESPECIFICO: 1}
    assert resumen.sesiones_sin_clasificar == 1


def test_resumen_suma_el_tiempo_real_en_cada_zona():
    resumen = resumir_periodo(SEMANA, LUNES, DOMINGO)
    assert resumen.duracion_por_zona == {
        ZonasFC.Z2: timedelta(seconds=900 + 3000 + 4200),
        ZonasFC.Z3: timedelta(seconds=600 + 3000),
        ZonasFC.Z4: timedelta(seconds=2100 + 1800),
    }


def test_resumen_ignora_sesiones_fuera_del_periodo():
    fuera = [_sesion(date(2026, 10, 11), 60, 12.0), _sesion(date(2026, 10, 19), 60, 12.0)]
    resumen = resumir_periodo(SEMANA + fuera, LUNES, DOMINGO)
    assert resumen.numero_sesiones == 4


def test_resumen_incluye_los_extremos_del_periodo():
    extremos = [_sesion(LUNES, 30, 5.0), _sesion(DOMINGO, 30, 5.0)]
    assert resumir_periodo(extremos, LUNES, DOMINGO).numero_sesiones == 2


def test_periodo_sin_sesiones_devuelve_ceros():
    resumen = resumir_periodo([], LUNES, DOMINGO)
    assert resumen.numero_sesiones == 0
    assert resumen.distancia_km == 0
    assert resumen.duracion == timedelta(0)
    assert resumen.sesiones_por_clase == {}


def test_resumir_periodo_rechaza_rango_invertido():
    with pytest.raises(ValueError):
        resumir_periodo(SEMANA, DOMINGO, LUNES)


def test_resumir_periodo_no_modifica_la_entrada():
    copia = [s.model_copy() for s in SEMANA]
    resumir_periodo(SEMANA, LUNES, DOMINGO)
    assert SEMANA == copia


# ---------- resumir_semanas ----------

def test_resumir_semanas_incluye_semanas_vacias_en_orden():
    sesiones = [
        _sesion(date(2026, 10, 6), 40, 7.0),   # semana del 5 oct
        _sesion(date(2026, 10, 20), 40, 7.0),  # semana del 19 oct
    ]
    semanas = resumir_semanas(sesiones, date(2026, 10, 7), date(2026, 10, 21))
    assert [s.fecha_inicio for s in semanas] == [date(2026, 10, 5), LUNES, date(2026, 10, 19)]
    assert [s.numero_sesiones for s in semanas] == [1, 0, 1]


def test_resumir_semanas_rechaza_rango_invertido():
    with pytest.raises(ValueError):
        resumir_semanas(SEMANA, DOMINGO, LUNES)


# ---------- variacion_pct ----------

@pytest.mark.parametrize(
    "anterior, actual, esperado",
    [(40, 44, 10.0), (40, 30, -25.0), (40, 40, 0.0), (30, 31, 3.3)],
)
def test_variacion_pct(anterior, actual, esperado):
    assert variacion_pct(anterior, actual) == esperado


def test_variacion_pct_sin_base_devuelve_none():
    assert variacion_pct(0, 25) is None


# ---------- carga ----------

def test_carga_srpe_es_rpe_por_minutos():
    assert carga_srpe(_sesion(LUNES, 60, 10, rpe=7)) == 420


def test_carga_srpe_sin_rpe_es_none():
    assert carga_srpe(_sesion(LUNES, 60, 10)) is None


def test_resumen_lleva_epoc_y_srpe_por_separado():
    sesiones = [
        _sesion(date(2026, 10, 13), 60, 10, epoc=120, rpe=6),  # sRPE 360
        _sesion(date(2026, 10, 15), 30, 5, epoc=40),           # sin RPE
        _sesion(date(2026, 10, 17), 90, 15, rpe=5),            # sin EPOC, sRPE 450
    ]
    resumen = resumir_periodo(sesiones, LUNES, DOMINGO)
    assert (resumen.carga_epoc, resumen.sesiones_con_epoc) == (160, 2)
    assert (resumen.carga_srpe, resumen.sesiones_con_rpe) == (810, 2)


def _semana(lunes, sesiones):
    return resumir_periodo(sesiones, lunes, lunes + timedelta(days=6))


SEMANA_PREVIA = date(2026, 10, 5)


def test_comparar_carga_usa_epoc_si_esta_completo_en_ambos():
    anterior = _semana(SEMANA_PREVIA, [_sesion(date(2026, 10, 6), 60, 10, epoc=100, rpe=6)])
    actual = _semana(LUNES, [_sesion(date(2026, 10, 13), 60, 10, epoc=110, rpe=6)])
    comparacion = comparar_carga(anterior, actual)
    assert comparacion.fuente == FuenteCarga.EPOC
    assert comparacion.variacion_pct == 10.0


def test_comparar_carga_cae_a_srpe_si_falta_epoc():
    anterior = _semana(SEMANA_PREVIA, [_sesion(date(2026, 10, 6), 60, 10, epoc=100, rpe=5)])  # sRPE 300
    actual = _semana(LUNES, [_sesion(date(2026, 10, 13), 60, 10, rpe=6)])                     # sRPE 360
    comparacion = comparar_carga(anterior, actual)
    assert comparacion.fuente == FuenteCarga.SRPE
    assert (comparacion.anterior, comparacion.actual) == (300, 360)
    assert comparacion.variacion_pct == 20.0


def test_comparar_carga_sin_fuente_completa_devuelve_none():
    anterior = _semana(SEMANA_PREVIA, [_sesion(date(2026, 10, 6), 60, 10, epoc=100)])
    actual = _semana(LUNES, [_sesion(date(2026, 10, 13), 60, 10, rpe=6)])
    assert comparar_carga(anterior, actual) is None
