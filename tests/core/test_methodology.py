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
    ReglaConteoMicrociclo,
    RegistroRegla,
    SecuenciaBloques,
    RegistroReglaSecuencial,
    RestriccionGlobal,
)
from core.training import ClaseSesion, ModoPlan, ObjetivoMesociclo


def _regla_progresion() -> RegistroRegla:
    return RegistroRegla(
        id="LYDIARD-PROGRESION-001",
        categoria=CategoriaRegla.PROGRESION,
        descripcion="El volumen semanal no debe subir más del 10% respecto a la semana anterior.",
        objetivo_mesociclo=ObjetivoMesociclo.BASE_AEROBICA,
        parametros={"incremento_maximo_pct": 10},
    )


def _regla_secuencial_fondo() -> RegistroReglaSecuencial:
    return RegistroReglaSecuencial(
        id="LYDIARD-SECUENCIA-001",
        descripcion="Después de Fondo, solo Recuperación o Descanso.",
        clase_sesion_previa=ClaseSesion.FONDO,
        clases_permitidas_despues=[ClaseSesion.RECUPERACION, ClaseSesion.DESCANSO],
    )


def _regla_conteo_descanso() -> ReglaConteoMicrociclo:
    return ReglaConteoMicrociclo(
        id="LYDIARD-CONTEO-001",
        descripcion="Mínimo 1 Descanso por microciclo.",
        clase_sesion=ClaseSesion.DESCANSO,
        minimo=1,
    )


def _perfil_base(**overrides) -> PerfilMetodologia:
    campos = dict(
        autor="Lydiard",
        fuente="https://example.com/lydiard",
        version="0.1.0",
        deportes_soportados=["running", "trail running"],
        reglas=[_regla_progresion()],
        reglas_secuenciales=[_regla_secuencial_fondo()],
        reglas_conteo_microciclo=[_regla_conteo_descanso()],
    )
    campos.update(overrides)
    return PerfilMetodologia(**campos)


# ---------- PerfilMetodologia ----------

def test_perfil_valido_se_construye():
    perfil = _perfil_base()
    assert perfil.autor == "Lydiard"
    assert len(perfil.reglas) == 1
    assert len(perfil.reglas_secuenciales) == 1
    assert len(perfil.reglas_conteo_microciclo) == 1


def test_perfil_rechaza_reglas_vacio():
    with pytest.raises(ValueError):
        _perfil_base(reglas=[])


def test_perfil_rechaza_id_duplicado_entre_listas_distintas():
    # Mismo id en `reglas` y en `reglas_conteo_microciclo` — validar_ids_unicos
    # debe detectarlo aunque estén en listas de tipos distintos.
    regla_dup = RegistroRegla(
        id="DUP-001", categoria=CategoriaRegla.CARGA, descripcion="Regla de carga."
    )
    conteo_dup = ReglaConteoMicrociclo(
        id="DUP-001",
        descripcion="Conteo duplicado.",
        clase_sesion=ClaseSesion.DESCANSO,
        minimo=1,
    )
    with pytest.raises(ValueError):
        _perfil_base(reglas=[regla_dup], reglas_conteo_microciclo=[conteo_dup])


# ---------- RegistroReglaSecuencial ----------

def test_regla_secuencial_permite_lo_declarado():
    regla = _regla_secuencial_fondo()
    assert ClaseSesion.RECUPERACION in regla.clases_permitidas_despues
    assert ClaseSesion.ESPECIFICO not in regla.clases_permitidas_despues


def test_regla_secuencial_rechaza_lista_vacia():
    with pytest.raises(ValueError):
        RegistroReglaSecuencial(
            id="X-001",
            descripcion="Lista vacía no tiene sentido.",
            clase_sesion_previa=ClaseSesion.FONDO,
            clases_permitidas_despues=[],
        )


# ---------- ReglaConteoMicrociclo ----------

def test_conteo_rechaza_sin_minimo_ni_maximo():
    with pytest.raises(ValueError):
        ReglaConteoMicrociclo(
            id="X-002",
            descripcion="Sin límite no dice nada.",
            clase_sesion=ClaseSesion.DESCANSO,
        )


def test_conteo_rechaza_minimo_mayor_que_maximo():
    with pytest.raises(ValueError):
        ReglaConteoMicrociclo(
            id="X-003",
            descripcion="Rango invertido.",
            clase_sesion=ClaseSesion.ESPECIFICO,
            minimo=5,
            maximo=2,
        )


def test_conteo_valido_con_solo_minimo():
    regla = ReglaConteoMicrociclo(
        id="X-004",
        descripcion="Al menos 1 Descanso.",
        clase_sesion=ClaseSesion.DESCANSO,
        minimo=1,
    )
    assert regla.minimo == 1
    assert regla.maximo is None


# ---------- RestriccionGlobal ----------

def test_restriccion_global_valida_con_parametros():
    restriccion = RestriccionGlobal(
        id="LYDIARD-GLOBAL-001",
        descripcion="No más de 3 microciclos de carga seguidos sin descarga.",
        parametros={"microciclos_carga_max": 3},
    )
    assert restriccion.parametros["microciclos_carga_max"] == 3


# ---------- ReglaAjuste ----------

def _regla_ajuste(**overrides) -> ReglaAjuste:
    campos = dict(
        id="LYDIARD-AJUSTE-001",
        descripcion="Si se cumplió menos del 70% del volumen, repetir la semana.",
        condicion=CondicionAjuste(
            metrica=MetricaAjuste.ADHERENCIA_VOLUMEN_PCT,
            operador=OperadorComparacion.MENOR,
            valor=70,
        ),
        accion=AccionAjuste.REPETIR_MICROCICLO,
        origen=OrigenRegla.PROPIO,
    )
    campos.update(overrides)
    return ReglaAjuste(**campos)


def test_regla_ajuste_valida():
    regla = _regla_ajuste(parametros={"cambio_carga_pct": 5})
    assert regla.accion == AccionAjuste.REPETIR_MICROCICLO
    assert regla.parametros["cambio_carga_pct"] == 5


def test_regla_ajuste_rechaza_accion_fuera_de_la_lista():
    with pytest.raises(ValueError):
        _regla_ajuste(accion="inventar_semana")


def test_regla_ajuste_rechaza_metrica_que_el_motor_no_mide():
    with pytest.raises(ValueError):
        CondicionAjuste(metrica="horas_de_sueno", operador="<", valor=7)


def test_regla_ajuste_exige_origen():
    campos = _regla_ajuste().model_dump(exclude={"origen"})
    with pytest.raises(ValueError):
        ReglaAjuste(**campos)


def test_perfil_rechaza_id_duplicado_en_reglas_ajuste():
    with pytest.raises(ValueError, match="duplicados"):
        _perfil_base(reglas_ajuste=[_regla_ajuste(id="LYDIARD-PROGRESION-001")])


# ---------- SecuenciaBloques ----------

def _secuencia(id_="LYDIARD-BLOQUES-001", modo=ModoPlan.CONSTRUCCION, objetivos=None) -> SecuenciaBloques:
    return SecuenciaBloques(
        id=id_,
        descripcion="Base y después fuerza.",
        modo=modo,
        objetivos=[ObjetivoMesociclo.BASE_AEROBICA, ObjetivoMesociclo.FUERZA_Y_ECONOMIA] if objetivos is None else objetivos,
    )


def test_secuencia_para_devuelve_la_del_modo():
    perfil = _perfil_base(secuencias_bloques=[_secuencia()])
    assert perfil.secuencia_para(ModoPlan.CONSTRUCCION).id == "LYDIARD-BLOQUES-001"
    assert perfil.secuencia_para(ModoPlan.COMPETICION) is None


def test_secuencia_rechaza_lista_vacia():
    with pytest.raises(ValueError):
        _secuencia(objetivos=[])


def test_perfil_rechaza_dos_secuencias_para_el_mismo_modo():
    with pytest.raises(ValueError, match="Más de una secuencia"):
        _perfil_base(secuencias_bloques=[_secuencia(), _secuencia(id_="LYDIARD-BLOQUES-002")])


def test_ids_de_las_secuencias_cuentan_como_ids_del_perfil():
    perfil = _perfil_base(secuencias_bloques=[_secuencia()])
    assert "LYDIARD-BLOQUES-001" in perfil.todos_los_ids()
    with pytest.raises(ValueError, match="duplicados"):
        _perfil_base(secuencias_bloques=[_secuencia(id_="LYDIARD-PROGRESION-001")])
