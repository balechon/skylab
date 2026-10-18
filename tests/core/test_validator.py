from datetime import date, timedelta
from pathlib import Path

from core.methodology import (
    CategoriaRegla,
    PerfilMetodologia,
    ReglaConteoMicrociclo,
    RegistroRegla,
    RegistroReglaSecuencial,
    RestriccionGlobal,
    SecuenciaBloques,
)
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
    TipoMicrociclo,
    TipoSesion,
    ZonasFC,
)
from core.loader import cargar_perfil
from core.validator import validar_plan

LUNES = date(2026, 10, 12)

# Las sesiones de Series necesitan su estructura para poder enviarse al reloj.
SERIES_6x3 = Intervalos(repeticiones=6, trabajo=timedelta(minutes=3), recuperacion=timedelta(minutes=2))

PERFILES_DIR = Path(__file__).parents[2] / "methodology" / "profiles"

CARGA, DESCARGA = TipoMicrociclo.CARGA, TipoMicrociclo.DESCARGA


# ---------- constructores ----------

def _sesion(dia: int, clase: ClaseSesion, tipo=None, zona=None, semana: int = 0) -> SesionPlanificada:
    fecha = LUNES + timedelta(weeks=semana, days=dia)
    if clase == ClaseSesion.DESCANSO:
        return SesionPlanificada(fecha=fecha, clase_sesion=clase)
    return SesionPlanificada(
        fecha=fecha, clase_sesion=clase, tipo_sesion=tipo, distancia_objetivo_km=8, zona_fc_objetivo=zona,
        intervalos=SERIES_6x3 if tipo == TipoSesion.SERIES else None,
    )


def _micro(semana: int, tipo=CARGA, km=None, horas=None, sesiones=None, por_clase=None) -> Microciclo:
    inicio = LUNES + timedelta(weeks=semana)
    return Microciclo(
        fecha_inicio=inicio,
        fecha_fin=inicio + timedelta(days=6),
        tipo_microciclo=tipo,
        objetivos=ObjetivosMicrociclo(
            volumen_km=km if km is not None or horas is not None else 40,
            duracion=timedelta(hours=horas) if horas is not None else None,
            sesiones_por_clase=por_clase or {},
        ),
        sesiones=sesiones or [],
    )


def _plan(*mesociclos: tuple[ObjetivoMesociclo, list[Microciclo]], modo=ModoPlan.CONSTRUCCION, carrera=None) -> Plan:
    mesos = []
    for objetivo, micros in mesociclos:
        mesos.append(
            Mesociclo(
                objetivo=objetivo,
                fecha_inicio=micros[0].fecha_inicio,
                fecha_fin=micros[-1].fecha_fin,
                microciclos=micros,
            )
        )
    fin = carrera.fecha if carrera else mesos[-1].fecha_fin
    return Plan(modo=modo, fecha_inicio=LUNES, fecha_objetivo=fin, carrera=carrera, mesociclos=mesos)


def _perfil(**listas) -> PerfilMetodologia:
    # PerfilMetodologia exige al menos una regla en `reglas`; esta de relleno
    # solo aplica a sesiones de Umbral, que ningún test usa.
    relleno = RegistroRegla(
        id="X-RELLENO-001",
        categoria=CategoriaRegla.INTENSIDAD,
        descripcion="Relleno.",
        tipo_sesion=TipoSesion.UMBRAL,
        parametros={"zona_fc_minima": "Z3"},
    )
    listas.setdefault("reglas", [relleno])
    return PerfilMetodologia(autor="TEST", fuente="tests", version="0", deportes_soportados=["running"], **listas)


BASE = ObjetivoMesociclo.BASE_AEROBICA
FUERZA = ObjetivoMesociclo.FUERZA_Y_ECONOMIA


# ---------- reglas secuenciales ----------

SECUENCIA_FONDO = RegistroReglaSecuencial(
    id="X-SECUENCIA-001",
    descripcion="Después de Fondo, solo Recuperación o Descanso.",
    clase_sesion_previa=ClaseSesion.FONDO,
    clases_permitidas_despues=[ClaseSesion.RECUPERACION, ClaseSesion.DESCANSO],
)


def test_secuencial_detecta_clase_no_permitida():
    sesiones = [
        _sesion(1, ClaseSesion.FONDO, TipoSesion.BASE),
        _sesion(2, ClaseSesion.ESPECIFICO, TipoSesion.SERIES),
    ]
    resultado = validar_plan(_plan((BASE, [_micro(0, sesiones=sesiones)])), _perfil(reglas_secuenciales=[SECUENCIA_FONDO]))
    assert [v.regla_id for v in resultado.violaciones] == ["X-SECUENCIA-001"]
    assert resultado.violaciones[0].fecha == LUNES + timedelta(days=2)


def test_secuencial_ordena_por_fecha_no_por_posicion():
    # En la lista, Específico va antes; por fecha va después del Fondo.
    sesiones = [
        _sesion(3, ClaseSesion.ESPECIFICO, TipoSesion.SERIES),
        _sesion(1, ClaseSesion.FONDO, TipoSesion.BASE),
    ]
    resultado = validar_plan(_plan((BASE, [_micro(0, sesiones=sesiones)])), _perfil(reglas_secuenciales=[SECUENCIA_FONDO]))
    assert not resultado.valido


def test_secuencial_cumplida():
    sesiones = [
        _sesion(1, ClaseSesion.FONDO, TipoSesion.BASE),
        _sesion(2, ClaseSesion.RECUPERACION, TipoSesion.RECUPERACION),
    ]
    resultado = validar_plan(_plan((BASE, [_micro(0, sesiones=sesiones)])), _perfil(reglas_secuenciales=[SECUENCIA_FONDO]))
    assert resultado.valido
    assert "X-SECUENCIA-001" in resultado.reglas_evaluadas


# ---------- reglas de conteo ----------

MIN_DESCANSO = ReglaConteoMicrociclo(
    id="X-CONTEO-001", descripcion="Mínimo 1 Descanso.", clase_sesion=ClaseSesion.DESCANSO, minimo=1
)
MAX_ESPECIFICO = ReglaConteoMicrociclo(
    id="X-CONTEO-002", descripcion="Máximo 2 Específico.", clase_sesion=ClaseSesion.ESPECIFICO, maximo=2
)


def test_conteo_en_semana_detallada_cuenta_sesiones():
    sesiones = [_sesion(1, ClaseSesion.FONDO, TipoSesion.BASE)]
    resultado = validar_plan(_plan((BASE, [_micro(0, sesiones=sesiones)])), _perfil(reglas_conteo_microciclo=[MIN_DESCANSO]))
    assert "tiene 0 sesiones de Descanso" in resultado.violaciones[0].mensaje


def test_conteo_en_semana_de_objetivos_usa_los_objetivos():
    micro = _micro(0, por_clase={ClaseSesion.ESPECIFICO: 3, ClaseSesion.DESCANSO: 1})
    resultado = validar_plan(_plan((BASE, [micro])), _perfil(reglas_conteo_microciclo=[MIN_DESCANSO, MAX_ESPECIFICO]))
    assert [v.regla_id for v in resultado.violaciones] == ["X-CONTEO-002"]


# ---------- incremento máximo de volumen ----------

def _progresion(objetivo=None) -> RegistroRegla:
    return RegistroRegla(
        id="X-PROGRESION-001",
        categoria=CategoriaRegla.PROGRESION,
        descripcion="El volumen no sube más de un 10% por semana.",
        objetivo_mesociclo=objetivo,
        parametros={"incremento_maximo_pct": 10},
    )


def test_incremento_detecta_subida_excesiva():
    plan = _plan((BASE, [_micro(0, km=40), _micro(1, km=44), _micro(2, km=50)]))  # +10%, +13.6%
    resultado = validar_plan(plan, _perfil(reglas=[_progresion()]))
    assert len(resultado.violaciones) == 1
    assert "13.6%" in resultado.violaciones[0].mensaje


def test_incremento_compara_en_horas_si_ambas_semanas_las_tienen():
    plan = _plan((BASE, [_micro(0, horas=5), _micro(1, horas=6)]))  # +20%
    resultado = validar_plan(plan, _perfil(reglas=[_progresion()]))
    assert "duración" in resultado.violaciones[0].mensaje


def test_tras_descarga_se_vuelve_al_nivel_previo_y_se_progresa():
    # 40 -> 44 -> descarga 30 -> 48: +9% sobre la última carga (44), válido.
    plan = _plan((BASE, [_micro(0, km=40), _micro(1, km=44), _micro(2, DESCARGA, km=30), _micro(3, km=48)]))
    assert validar_plan(plan, _perfil(reglas=[_progresion()])).valido


def test_tras_descarga_un_salto_sigue_siendo_violacion():
    # 40 -> 44 -> descarga 30 -> 55: +25% sobre la última carga (44).
    plan = _plan((BASE, [_micro(0, km=40), _micro(1, km=44), _micro(2, DESCARGA, km=30), _micro(3, km=55)]))
    resultado = validar_plan(plan, _perfil(reglas=[_progresion()]))
    assert len(resultado.violaciones) == 1
    assert "25.0%" in resultado.violaciones[0].mensaje
    assert str(LUNES + timedelta(weeks=1)) in resultado.violaciones[0].mensaje  # referencia: la semana de 44


def test_incremento_solo_aplica_al_objetivo_de_la_regla():
    plan = _plan((BASE, [_micro(0, km=40)]), (FUERZA, [_micro(1, km=60)]))  # +50% en Fuerza
    assert validar_plan(plan, _perfil(reglas=[_progresion(objetivo=BASE)])).valido
    assert not validar_plan(plan, _perfil(reglas=[_progresion(objetivo=FUERZA)])).valido


# ---------- zona de FC mínima ----------

SERIES_Z4 = RegistroRegla(
    id="X-INTENSIDAD-001",
    categoria=CategoriaRegla.INTENSIDAD,
    descripcion="Las series van en Z4 o más.",
    tipo_sesion=TipoSesion.SERIES,
    parametros={"zona_fc_minima": "Z4"},
)


def test_zona_minima_detecta_zona_baja_y_zona_ausente():
    sesiones = [
        _sesion(1, ClaseSesion.ESPECIFICO, TipoSesion.SERIES, ZonasFC.Z3),
        _sesion(3, ClaseSesion.ESPECIFICO, TipoSesion.SERIES, None),
        _sesion(5, ClaseSesion.ESPECIFICO, TipoSesion.SERIES, ZonasFC.Z5),
        _sesion(6, ClaseSesion.ESPECIFICO, TipoSesion.TEMPO, ZonasFC.Z3),  # no es Series
    ]
    resultado = validar_plan(_plan((BASE, [_micro(0, sesiones=sesiones)])), _perfil(reglas=[SERIES_Z4]))
    assert len(resultado.violaciones) == 2
    assert "está en Z3" in resultado.violaciones[0].mensaje
    assert "no indica zona" in resultado.violaciones[1].mensaje


# ---------- carga consecutiva ----------

MAX_3_CARGAS = RestriccionGlobal(
    id="X-GLOBAL-001", descripcion="Máximo 3 cargas seguidas.", parametros={"microciclos_carga_max": 3}
)


def test_carga_consecutiva_cuenta_a_traves_de_mesociclos():
    plan = _plan((BASE, [_micro(0), _micro(1)]), (FUERZA, [_micro(2), _micro(3)]))
    resultado = validar_plan(plan, _perfil(restricciones_globales=[MAX_3_CARGAS]))
    assert [v.fecha for v in resultado.violaciones] == [LUNES + timedelta(weeks=3)]


def test_carga_consecutiva_se_reinicia_con_descarga():
    plan = _plan((BASE, [_micro(0), _micro(1), _micro(2), _micro(3, DESCARGA), _micro(4)]))
    assert validar_plan(plan, _perfil(restricciones_globales=[MAX_3_CARGAS])).valido


# ---------- semanas mínimas para carrera larga ----------

SEMANAS_MINIMAS = RestriccionGlobal(
    id="X-GLOBAL-002",
    descripcion="Carrera de más de 21 km: al menos 16 semanas.",
    parametros={"distancia_umbral_km": 21, "semanas_minimas": 16},
)


def test_semanas_minimas_en_competicion_corta():
    carrera = Carrera(nombre="Trail", fecha=LUNES + timedelta(weeks=4, days=6), distancia_km=42)
    plan = _plan((BASE, [_micro(i) for i in range(5)]), modo=ModoPlan.COMPETICION, carrera=carrera)
    resultado = validar_plan(plan, _perfil(restricciones_globales=[SEMANAS_MINIMAS]))
    assert "necesita al menos 16 semanas" in resultado.violaciones[0].mensaje


def test_semanas_minimas_no_aplica_en_construccion():
    plan = _plan((BASE, [_micro(0), _micro(1)]))
    assert validar_plan(plan, _perfil(restricciones_globales=[SEMANAS_MINIMAS])).valido


# ---------- reglas que el motor no sabe evaluar ----------

def test_parametros_desconocidos_no_se_dan_por_cumplidos():
    desconocida = RegistroRegla(
        id="X-CARGA-009",
        categoria=CategoriaRegla.CARGA,
        descripcion="Regla con un parámetro que el motor no conoce.",
        parametros={"ratio_agudo_cronico_max": 1.3},
    )
    resultado = validar_plan(_plan((BASE, [_micro(0)])), _perfil(reglas=[desconocida]))
    assert resultado.valido          # nada incumplido entre lo evaluado...
    assert not resultado.completo    # ...pero no todo se pudo comprobar
    assert "X-CARGA-009" not in resultado.reglas_evaluadas
    assert "ratio_agudo_cronico_max" in resultado.reglas_no_evaluables[0].motivo


# ---------- integración con el perfil didáctico ----------

def test_plan_correcto_cumple_todo_el_perfil_didactico():
    perfil = cargar_perfil(PERFILES_DIR / "ejemplo_didactico.yaml")
    semana_1 = [
        _sesion(0, ClaseSesion.DESCANSO),
        _sesion(1, ClaseSesion.ESPECIFICO, TipoSesion.SERIES, ZonasFC.Z4),
        _sesion(2, ClaseSesion.RECUPERACION, TipoSesion.RECUPERACION, ZonasFC.Z1),
        _sesion(3, ClaseSesion.FONDO, TipoSesion.BASE, ZonasFC.Z2),
        _sesion(4, ClaseSesion.DESCANSO),
    ]
    plan = _plan(
        (
            BASE,
            [
                _micro(0, km=40, sesiones=semana_1),
                _micro(1, km=44, por_clase={ClaseSesion.DESCANSO: 1, ClaseSesion.ESPECIFICO: 1}),
                _micro(2, km=48, por_clase={ClaseSesion.DESCANSO: 1, ClaseSesion.ESPECIFICO: 1}),
                _micro(3, DESCARGA, km=30, por_clase={ClaseSesion.DESCANSO: 2}),
            ],
        )
    )
    resultado = validar_plan(plan, perfil)
    assert resultado.violaciones == []
    assert resultado.completo
    assert len(resultado.reglas_evaluadas) == 11  # incluye la secuencia de construcción, no la de competición


# ---------- secuencia de bloques ----------

BLOQUES = SecuenciaBloques(
    id="X-BLOQUES-001",
    descripcion="Base y después fuerza.",
    modo=ModoPlan.CONSTRUCCION,
    objetivos=[BASE, FUERZA],
)


def test_secuencia_completa_en_orden_es_valida():
    plan = _plan((BASE, [_micro(0)]), (FUERZA, [_micro(1)]))
    resultado = validar_plan(plan, _perfil(secuencias_bloques=[BLOQUES]))
    assert resultado.valido and "X-BLOQUES-001" in resultado.reglas_evaluadas


def test_horizonte_corto_puede_usar_solo_los_primeros_bloques():
    plan = _plan((BASE, [_micro(0), _micro(1)]))
    assert validar_plan(plan, _perfil(secuencias_bloques=[BLOQUES])).valido


def test_bloque_fuera_de_orden_o_inventado_es_violacion():
    plan = _plan((BASE, [_micro(0)]), (ObjetivoMesociclo.UMBRAL, [_micro(1)]))
    resultado = validar_plan(plan, _perfil(secuencias_bloques=[BLOQUES]))
    assert "es Umbral; según la secuencia debe ser Fuerza y economía" in resultado.violaciones[0].mensaje


def test_mas_bloques_que_la_secuencia_es_violacion():
    plan = _plan((BASE, [_micro(0)]), (FUERZA, [_micro(1)]), (BASE, [_micro(2)]))
    resultado = validar_plan(plan, _perfil(secuencias_bloques=[BLOQUES]))
    assert any("solo define 2" in v.mensaje for v in resultado.violaciones)


def test_la_secuencia_de_otro_modo_no_se_evalua():
    competicion = BLOQUES.model_copy(update={"id": "X-BLOQUES-002", "modo": ModoPlan.COMPETICION})
    resultado = validar_plan(_plan((ObjetivoMesociclo.UMBRAL, [_micro(0)])), _perfil(secuencias_bloques=[competicion]))
    assert resultado.valido and "X-BLOQUES-002" not in resultado.reglas_evaluadas


# ---------- tipos de semana, reglas por tipo y por atleta ----------

from core.athlete import FichaAtleta, Umbrales, deficiencia_aerobica  # noqa: E402
from core.methodology import CondicionAtleta, TiposSemana  # noqa: E402

SEM_BASE, SEM_INTENSIDAD = TipoMicrociclo.BASE, TipoMicrociclo.INTENSIDAD


def _regla(rid: str, parametros: dict, **campos) -> RegistroRegla:
    return RegistroRegla(id=rid, categoria=CategoriaRegla.CARGA, descripcion="Prueba.", parametros=parametros, **campos)


def _con_duracion(dia: int, minutos: int, clase=ClaseSesion.FONDO, zona=ZonasFC.Z1, semana: int = 0) -> SesionPlanificada:
    return SesionPlanificada(
        fecha=LUNES + timedelta(weeks=semana, days=dia),
        clase_sesion=clase,
        tipo_sesion=TipoSesion.BASE,
        duracion_objetivo=timedelta(minutes=minutos),
        zona_fc_objetivo=zona,
    )


def test_las_semanas_de_base_cuentan_como_carga():
    perfil = _perfil(restricciones_globales=[RestriccionGlobal(id="G-1", descripcion="3:1", parametros={"microciclos_carga_max": 3})])
    plan = _plan((ObjetivoMesociclo.BASE_AEROBICA, [_micro(0, SEM_BASE), _micro(1, SEM_BASE), _micro(2, SEM_INTENSIDAD), _micro(3, SEM_BASE)]))
    violaciones = validar_plan(plan, perfil).violaciones
    assert [v.regla_id for v in violaciones] == ["G-1"]


def test_la_descarga_baja_entre_el_40_y_el_60_por_ciento():
    regla = _regla("R-DESCARGA", {"reduccion_descarga_min_pct": 40, "reduccion_descarga_max_pct": 60})
    perfil = _perfil(reglas=[regla])
    bien = _plan((ObjetivoMesociclo.BASE_AEROBICA, [_micro(0, SEM_BASE, horas=5), _micro(1, DESCARGA, horas=2.5)]))
    assert validar_plan(bien, perfil).violaciones == []
    poco = _plan((ObjetivoMesociclo.BASE_AEROBICA, [_micro(0, SEM_BASE, horas=5), _micro(1, DESCARGA, horas=4)]))
    violaciones = validar_plan(poco, perfil).violaciones
    assert len(violaciones) == 1 and "baja la duración un 20%" in violaciones[0].mensaje


def test_la_larga_es_al_menos_el_30_por_ciento_en_semanas_de_base():
    regla = _regla(
        "R-LARGA", {"larga_min_pct_semana": 30, "larga_max_pct_semana": 40},
        clase_sesion=ClaseSesion.FONDO, tipos_microciclo=[SEM_BASE, SEM_INTENSIDAD],
    )
    perfil = _perfil(reglas=[regla])
    # 4 × 60' + larga de 90' = 27 % → no llega.
    sesiones = [_con_duracion(d, 60) for d in (1, 2, 3, 5)] + [_con_duracion(6, 90)]
    corta = _plan((ObjetivoMesociclo.BASE_AEROBICA, [_micro(0, SEM_BASE, horas=5.5, sesiones=sesiones)]))
    violaciones = validar_plan(corta, perfil).violaciones
    assert len(violaciones) == 1 and "el 27.3% del tiempo semanal" in violaciones[0].mensaje
    # Con larga de 120' (33 %) cumple; y en una descarga la regla no aplica.
    sesiones[-1] = _con_duracion(6, 120)
    assert validar_plan(_plan((ObjetivoMesociclo.BASE_AEROBICA, [_micro(0, SEM_BASE, horas=6, sesiones=sesiones)])), perfil).violaciones == []
    sesiones[-1] = _con_duracion(6, 30)
    assert validar_plan(_plan((ObjetivoMesociclo.BASE_AEROBICA, [_micro(0, DESCARGA, horas=4.5, sesiones=sesiones)])), perfil).violaciones == []


def test_z2_como_maximo_15_por_ciento_salvo_deficiencia_aerobica():
    regla = _regla("R-Z2", {"z2_max_pct_semanal": 15}, solo_si=CondicionAtleta.SIN_DEFICIENCIA_AEROBICA)
    perfil = _perfil(reglas=[regla], deficiencia_aerobica_pct=10)
    sesiones = [_con_duracion(1, 60, zona=ZonasFC.Z2), _con_duracion(3, 60), _con_duracion(6, 120)]
    plan = _plan((ObjetivoMesociclo.BASE_AEROBICA, [_micro(0, SEM_BASE, horas=4, sesiones=sesiones)]))

    sin_deficit = FichaAtleta(edad=31, umbrales=Umbrales(fc_aerobico=160, fc_lactato=172))  # 7,5 %
    violaciones = validar_plan(plan, perfil, sin_deficit).violaciones
    assert len(violaciones) == 1 and "son el 25% del tiempo semanal" in violaciones[0].mensaje

    con_deficit = FichaAtleta(edad=31, umbrales=Umbrales(fc_aerobico=149, fc_lactato=172))  # 15 %
    resultado = validar_plan(plan, perfil, con_deficit)
    assert resultado.violaciones == [] and "R-Z2" in resultado.reglas_evaluadas

    # Sin umbral de lactato no se sabe: no evaluable, nunca "cumplida".
    sin_lt = validar_plan(plan, perfil, FichaAtleta(edad=31, umbrales=Umbrales(fc_aerobico=149)))
    assert [r.regla_id for r in sin_lt.reglas_no_evaluables] == ["R-Z2"]
    assert "R-Z2" not in sin_lt.reglas_evaluadas


def test_conteo_segun_deficiencia_aerobica():
    reglas = [
        ReglaConteoMicrociclo(id="C-2", descripcion=".", clase_sesion=ClaseSesion.ESPECIFICO, maximo=2,
                              solo_si=CondicionAtleta.SIN_DEFICIENCIA_AEROBICA),
        ReglaConteoMicrociclo(id="C-1", descripcion=".", clase_sesion=ClaseSesion.ESPECIFICO, maximo=1,
                              solo_si=CondicionAtleta.CON_DEFICIENCIA_AEROBICA),
    ]
    perfil = _perfil(reglas_conteo_microciclo=reglas, deficiencia_aerobica_pct=10)
    dos_intensas = _plan((ObjetivoMesociclo.BASE_AEROBICA, [_micro(0, SEM_BASE, por_clase={ClaseSesion.ESPECIFICO: 2})]))
    con_deficit = FichaAtleta(edad=31, umbrales=Umbrales(fc_aerobico=149, fc_lactato=172))
    assert [v.regla_id for v in validar_plan(dos_intensas, perfil, con_deficit).violaciones] == ["C-1"]
    sin_deficit = FichaAtleta(edad=31, umbrales=Umbrales(fc_aerobico=160, fc_lactato=172))
    assert validar_plan(dos_intensas, perfil, sin_deficit).violaciones == []


def test_solo_se_usan_los_tipos_de_semana_del_perfil():
    tipos = TiposSemana(id="T-1", descripcion=".", tipos={SEM_BASE: "B", DESCARGA: "R"})
    perfil = _perfil(tipos_semana=tipos)
    plan = _plan((ObjetivoMesociclo.BASE_AEROBICA, [_micro(0, SEM_BASE), _micro(1, CARGA)]))
    violaciones = validar_plan(plan, perfil).violaciones
    assert [v.regla_id for v in violaciones] == ["T-1"] and "tipo Carga" in violaciones[0].mensaje


def test_deficiencia_aerobica_es_el_test_del_10_por_ciento():
    assert deficiencia_aerobica(Umbrales(fc_aerobico=149, fc_lactato=170), 10) is True  # 14 %
    assert deficiencia_aerobica(Umbrales(fc_aerobico=160, fc_lactato=172), 10) is False  # 7,5 %
    assert deficiencia_aerobica(Umbrales(fc_aerobico=149), 10) is None



# ---------- desnivel ----------

def _micro_dmas(semana: int, desnivel: float, tipo=SEM_BASE, horas: float = 5) -> Microciclo:
    micro = _micro(semana, tipo, horas=horas)
    micro.objetivos.desnivel_positivo_m = desnivel
    return micro


REGLA_DESNIVEL = _regla("R-DMAS", {"incremento_desnivel_max_pct": 10, "incremento_desnivel_4_semanas_max_pct": 20})


def test_el_desnivel_sube_como_mucho_un_10_por_ciento_por_semana():
    plan = _plan((ObjetivoMesociclo.BASE_AEROBICA, [_micro_dmas(0, 1000), _micro_dmas(1, 1100), _micro_dmas(2, 1250)]))
    violaciones = validar_plan(plan, _perfil(reglas=[REGLA_DESNIVEL])).violaciones
    assert len(violaciones) == 1 and "sube el desnivel un 13.6%" in violaciones[0].mensaje


def test_el_desnivel_sube_como_mucho_un_20_por_ciento_en_cuatro_semanas():
    # +7 % por semana durante tres semanas, descarga y vuelta: +22 % frente a
    # la semana 0 cuatro semanas después.
    semanas = [
        _micro_dmas(0, 1000), _micro_dmas(1, 1070), _micro_dmas(2, 1140),
        _micro_dmas(3, 600, tipo=DESCARGA, horas=2.5), _micro_dmas(4, 1220),
    ]
    violaciones = validar_plan(_plan((ObjetivoMesociclo.BASE_AEROBICA, semanas)), _perfil(reglas=[REGLA_DESNIVEL])).violaciones
    assert [v.fecha for v in violaciones] == [LUNES + timedelta(weeks=4)]
    assert "cuatro semanas antes" in violaciones[0].mensaje


def test_la_descarga_tambien_baja_el_desnivel():
    regla = _regla("R-DESCARGA", {"reduccion_descarga_min_pct": 40, "reduccion_descarga_max_pct": 60})
    plan = _plan((ObjetivoMesociclo.BASE_AEROBICA, [_micro_dmas(0, 1000), _micro_dmas(1, 900, tipo=DESCARGA, horas=2.5)]))
    violaciones = validar_plan(plan, _perfil(reglas=[regla])).violaciones
    assert len(violaciones) == 1 and "baja el desnivel un 10%" in violaciones[0].mensaje
