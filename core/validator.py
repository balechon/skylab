# Valida un plan propuesto contra el perfil de metodología activo.
#
# Es la única autoridad sobre "¿esto cumple la metodología?". Función pura:
# recibe un Plan y un PerfilMetodologia y devuelve un ResultadoValidacion,
# sin IO ni LLM.
#
# Las reglas con parámetros libres (RegistroRegla, RestriccionGlobal) solo se
# pueden evaluar si el motor conoce sus parámetros. Una regla que no sabe
# evaluar NO se da por cumplida: se reporta en reglas_no_evaluables, para que
# nadie confunda "no comprobado" con "válido".
#
# Las reglas_ajuste no se validan aquí: deciden cómo reaccionar a una semana
# ya realizada, y eso es trabajo de deviation.py.

from datetime import date, timedelta
from typing import Callable, Iterator, Optional

from pydantic import BaseModel, Field

from core.athlete import FichaAtleta, condiciones_atleta
from core.methodology import (
    CondicionAtleta,
    PerfilMetodologia,
    RegistroRegla,
    RegistroReglaSecuencial,
    ReglaConteoMicrociclo,
    RestriccionGlobal,
    SecuenciaBloques,
    TiposSemana,
)
from core.training import (
    Mesociclo,
    Microciclo,
    Plan,
    ClaseSesion,
    SesionPlanificada,
    TipoMicrociclo,
    ZonasFC,
)
from core.calculator import variacion_pct


class Violacion(BaseModel):
    regla_id: str
    mensaje: str
    fecha: Optional[date] = None  # dónde ocurre, si aplica


class ReglaNoEvaluable(BaseModel):
    regla_id: str
    motivo: str


class ResultadoValidacion(BaseModel):
    violaciones: list[Violacion] = Field(default_factory=list)
    reglas_evaluadas: list[str] = Field(default_factory=list)
    reglas_no_evaluables: list[ReglaNoEvaluable] = Field(default_factory=list)

    @property
    def valido(self) -> bool:
        """Ninguna regla evaluada se incumple."""
        return not self.violaciones

    @property
    def completo(self) -> bool:
        """Todas las reglas del perfil se pudieron evaluar."""
        return not self.reglas_no_evaluables


# ---------- recorridos del plan ----------

def _microciclos(plan: Plan) -> Iterator[tuple[Microciclo, Mesociclo]]:
    """Todos los microciclos del plan en orden, con su mesociclo."""
    for meso in plan.mesociclos:
        for micro in meso.microciclos:
            yield micro, meso


def _sesiones(plan: Plan) -> Iterator[tuple[SesionPlanificada, Microciclo, Mesociclo]]:
    for micro, meso in _microciclos(plan):
        for sesion in micro.sesiones:
            yield sesion, micro, meso


def _aplica_a_sesion(regla: RegistroRegla, sesion: SesionPlanificada, meso: Mesociclo) -> bool:
    return (
        (regla.objetivo_mesociclo is None or regla.objetivo_mesociclo == meso.objetivo)
        and (regla.clase_sesion is None or regla.clase_sesion == sesion.clase_sesion)
        and (regla.tipo_sesion is None or regla.tipo_sesion == sesion.tipo_sesion)
    )


def _aplica_a_semana(regla: RegistroRegla, micro: Microciclo, meso: Mesociclo) -> bool:
    return (regla.objetivo_mesociclo is None or regla.objetivo_mesociclo == meso.objetivo) and (
        not regla.tipos_microciclo or micro.tipo_microciclo in regla.tipos_microciclo
    )


def _tiempo_por_sesion(micro: Microciclo) -> Optional[list[tuple[SesionPlanificada, float]]]:
    """Minutos de cada sesión con carga de una semana detallada, o None si
    alguna no tiene duración (entonces no se puede medir en tiempo)."""
    con_carga = [s for s in micro.sesiones if s.clase_sesion != ClaseSesion.DESCANSO]
    if any(s.duracion_objetivo is None for s in con_carga):
        return None
    return [(s, s.duracion_objetivo / timedelta(minutes=1)) for s in con_carga]


# ---------- comprobaciones por parámetro conocido ----------

def _max_carga_consecutiva(plan: Plan, regla_id: str, maximo: int) -> list[Violacion]:
    """No más de `maximo` microciclos de carga seguidos sin una descarga,
    contando a través de mesociclos."""
    violaciones = []
    seguidos = 0
    for micro, _ in _microciclos(plan):
        if micro.tipo_microciclo.es_carga:
            seguidos += 1
            if seguidos == maximo + 1:
                violaciones.append(
                    Violacion(
                        regla_id=regla_id,
                        fecha=micro.fecha_inicio,
                        mensaje=(
                            f"La semana del {micro.fecha_inicio} es la {seguidos}ª de carga "
                            f"seguida; el máximo sin descarga es {maximo}."
                        ),
                    )
                )
        else:
            seguidos = 0
    return violaciones


def _reduccion_descarga(plan: Plan, regla: RegistroRegla, minimo: float, maximo: float) -> list[Violacion]:
    """Cada semana de descarga baja el volumen entre `minimo` y `maximo` %
    respecto a la última semana de carga anterior."""
    violaciones = []
    referencia: Optional[Microciclo] = None
    for micro, meso in _microciclos(plan):
        if micro.tipo_microciclo.es_carga:
            referencia = micro
            continue
        if micro.tipo_microciclo != TipoMicrociclo.DESCARGA or referencia is None:
            continue
        if not _aplica_a_semana(regla, micro, meso):
            continue
        comparable = _volumen_comparable(referencia, micro)
        cambio = variacion_pct(comparable[1], comparable[2]) if comparable else None
        if cambio is None:
            continue
        reduccion = -cambio
        if not minimo <= reduccion <= maximo:
            violaciones.append(
                Violacion(
                    regla_id=regla.id,
                    fecha=micro.fecha_inicio,
                    mensaje=(
                        f"La descarga del {micro.fecha_inicio} baja la {comparable[0]} un {reduccion:g}% respecto a "
                        f"la semana de carga del {referencia.fecha_inicio}; debe bajar entre {minimo:g} y {maximo:g}%."
                    ),
                )
            )
    return violaciones


def _proporcion_larga(plan: Plan, regla: RegistroRegla, minimo: float) -> list[Violacion]:
    """En las semanas detalladas a las que aplica, la sesión más larga (de la
    clase de la regla, si la fija) es al menos `minimo` % del tiempo semanal.

    El máximo de la regla no se comprueba: el libro admite superarlo en las
    semanas de poco volumen, así que queda como guía para el agente."""
    violaciones = []
    for micro, meso in _microciclos(plan):
        if not micro.detallado or not _aplica_a_semana(regla, micro, meso):
            continue
        tiempos = _tiempo_por_sesion(micro)
        if not tiempos:
            continue
        total = sum(minutos for _, minutos in tiempos)
        candidatas = [m for s, m in tiempos if regla.clase_sesion is None or s.clase_sesion == regla.clase_sesion]
        larga = max(candidatas, default=0)
        pct = round(100 * larga / total, 1)
        if pct < minimo:
            violaciones.append(
                Violacion(
                    regla_id=regla.id,
                    fecha=micro.fecha_inicio,
                    mensaje=(
                        f"En la semana del {micro.fecha_inicio} la sesión larga es el {pct:g}% del tiempo semanal; "
                        f"debe ser al menos el {minimo:g}%."
                    ),
                )
            )
    return violaciones


def _zona_max_semanal(plan: Plan, regla: RegistroRegla, zona: ZonasFC, maximo: float) -> list[Violacion]:
    """En las semanas detalladas a las que aplica, las sesiones en `zona` no
    pasan del `maximo` % del tiempo semanal."""
    violaciones = []
    for micro, meso in _microciclos(plan):
        if not micro.detallado or not _aplica_a_semana(regla, micro, meso):
            continue
        tiempos = _tiempo_por_sesion(micro)
        if not tiempos:
            continue
        total = sum(minutos for _, minutos in tiempos)
        en_zona = sum(m for s, m in tiempos if s.zona_fc_objetivo == zona)
        pct = round(100 * en_zona / total, 1)
        if pct > maximo:
            violaciones.append(
                Violacion(
                    regla_id=regla.id,
                    fecha=micro.fecha_inicio,
                    mensaje=(
                        f"En la semana del {micro.fecha_inicio} las sesiones en {zona.value} son el {pct:g}% del "
                        f"tiempo semanal; el máximo es {maximo:g}%."
                    ),
                )
            )
    return violaciones


def _volumen_comparable(anterior: Microciclo, actual: Microciclo) -> Optional[tuple[str, float, float]]:
    """Volumen objetivo de dos semanas en la misma unidad: tiempo si ambas lo
    tienen, si no km. None si no comparten unidad."""
    a, b = anterior.objetivos, actual.objetivos
    if a.duracion is not None and b.duracion is not None:
        return "duración", a.duracion / timedelta(hours=1), b.duracion / timedelta(hours=1)
    if a.volumen_km is not None and b.volumen_km is not None:
        return "volumen", a.volumen_km, b.volumen_km
    return None


def _incremento_maximo(plan: Plan, regla: RegistroRegla, maximo_pct: float) -> list[Violacion]:
    """El volumen de una semana de carga no sube más de `maximo_pct` respecto
    a la semana de carga anterior.

    Las semanas de descarga no cuentan como referencia: tras una descarga se
    vuelve al nivel previo y se sigue progresando, así que la primera semana
    de carga después se compara con la última de carga antes de la descarga
    (40 → descarga 30 → 44 es +10%), nunca con la descarga (que daría +47%
    y permitiría saltos grandes)."""
    violaciones = []
    referencia: Optional[Microciclo] = None
    for micro, meso in _microciclos(plan):
        if not micro.tipo_microciclo.es_carga:
            continue
        aplica = regla.objetivo_mesociclo is None or regla.objetivo_mesociclo == meso.objetivo
        if aplica and referencia is not None:
            comparable = _volumen_comparable(referencia, micro)
            if comparable is not None:
                unidad, anterior, actual = comparable
                cambio = variacion_pct(anterior, actual)
                if cambio is not None and cambio > maximo_pct:
                    violaciones.append(
                        Violacion(
                            regla_id=regla.id,
                            fecha=micro.fecha_inicio,
                            mensaje=(
                                f"La semana del {micro.fecha_inicio} sube la {unidad} un {cambio}% "
                                f"respecto a la semana de carga del {referencia.fecha_inicio}; "
                                f"el máximo es {maximo_pct}%."
                            ),
                        )
                    )
        referencia = micro
    return violaciones


_ORDEN_ZONAS = list(ZonasFC)


def _zona_minima(plan: Plan, regla: RegistroRegla, zona_minima: ZonasFC) -> list[Violacion]:
    """Las sesiones a las que aplica la regla deben prescribir una zona de FC
    igual o superior a `zona_minima`."""
    violaciones = []
    for sesion, _, meso in _sesiones(plan):
        if not _aplica_a_sesion(regla, sesion, meso):
            continue
        if sesion.zona_fc_objetivo is None:
            mensaje = f"La sesión del {sesion.fecha} no indica zona de FC; debe ser {zona_minima.value} o superior."
        elif _ORDEN_ZONAS.index(sesion.zona_fc_objetivo) < _ORDEN_ZONAS.index(zona_minima):
            mensaje = (
                f"La sesión del {sesion.fecha} está en {sesion.zona_fc_objetivo.value}; "
                f"debe ser {zona_minima.value} o superior."
            )
        else:
            continue
        violaciones.append(Violacion(regla_id=regla.id, fecha=sesion.fecha, mensaje=mensaje))
    return violaciones


def _semanas_minimas(plan: Plan, regla_id: str, distancia_umbral_km: float, semanas_minimas: int) -> list[Violacion]:
    """Un plan hacia una carrera más larga que el umbral necesita al menos
    `semanas_minimas` de preparación."""
    if plan.carrera is None or plan.carrera.distancia_km <= distancia_umbral_km:
        return []
    semanas = ((plan.fecha_objetivo - plan.fecha_inicio).days + 1) / 7
    if semanas >= semanas_minimas:
        return []
    return [
        Violacion(
            regla_id=regla_id,
            fecha=plan.fecha_inicio,
            mensaje=(
                f"La carrera de {plan.carrera.distancia_km} km supera {distancia_umbral_km} km y "
                f"necesita al menos {semanas_minimas} semanas; el plan tiene {semanas:.1f}."
            ),
        )
    ]


# Qué parámetros sabe evaluar el motor, y con qué función. Una regla se
# evalúa si sus parámetros coinciden con una de estas firmas.
_EvaluadorRegla = Callable[[Plan, RegistroRegla], list[Violacion]]
_EvaluadorRestriccion = Callable[[Plan, RestriccionGlobal], list[Violacion]]

_EVALUADORES_REGLA: dict[frozenset[str], _EvaluadorRegla] = {
    frozenset({"incremento_maximo_pct"}): lambda plan, r: _incremento_maximo(
        plan, r, float(r.parametros["incremento_maximo_pct"])
    ),
    frozenset({"zona_fc_minima"}): lambda plan, r: _zona_minima(
        plan, r, ZonasFC(r.parametros["zona_fc_minima"])
    ),
    frozenset({"microciclos_carga_antes_descarga"}): lambda plan, r: _max_carga_consecutiva(
        plan, r.id, int(r.parametros["microciclos_carga_antes_descarga"])
    ),
    frozenset({"reduccion_descarga_min_pct", "reduccion_descarga_max_pct"}): lambda plan, r: _reduccion_descarga(
        plan, r, float(r.parametros["reduccion_descarga_min_pct"]), float(r.parametros["reduccion_descarga_max_pct"])
    ),
    frozenset({"larga_min_pct_semana", "larga_max_pct_semana"}): lambda plan, r: _proporcion_larga(
        plan, r, float(r.parametros["larga_min_pct_semana"])
    ),
    frozenset({"z2_max_pct_semanal"}): lambda plan, r: _zona_max_semanal(
        plan, r, ZonasFC.Z2, float(r.parametros["z2_max_pct_semanal"])
    ),
}

_EVALUADORES_RESTRICCION: dict[frozenset[str], _EvaluadorRestriccion] = {
    frozenset({"microciclos_carga_max"}): lambda plan, r: _max_carga_consecutiva(
        plan, r.id, int(r.parametros["microciclos_carga_max"])
    ),
    frozenset({"distancia_umbral_km", "semanas_minimas"}): lambda plan, r: _semanas_minimas(
        plan, r.id, float(r.parametros["distancia_umbral_km"]), int(r.parametros["semanas_minimas"])
    ),
}


# ---------- reglas con forma fija ----------

def _secuencial(plan: Plan, regla: RegistroReglaSecuencial) -> list[Violacion]:
    """Dentro de cada microciclo, lo que sigue a `clase_sesion_previa` debe
    estar en `clases_permitidas_despues`."""
    violaciones = []
    for micro, _ in _microciclos(plan):
        ordenadas = sorted(micro.sesiones, key=lambda s: s.fecha)
        for previa, siguiente in zip(ordenadas, ordenadas[1:]):
            if (
                previa.clase_sesion == regla.clase_sesion_previa
                and siguiente.clase_sesion not in regla.clases_permitidas_despues
            ):
                permitidas = ", ".join(c.value for c in regla.clases_permitidas_despues)
                violaciones.append(
                    Violacion(
                        regla_id=regla.id,
                        fecha=siguiente.fecha,
                        mensaje=(
                            f"El {siguiente.fecha} hay {siguiente.clase_sesion.value} justo después de "
                            f"{previa.clase_sesion.value} ({previa.fecha}); solo se permite: {permitidas}."
                        ),
                    )
                )
    return violaciones


def _conteo(plan: Plan, regla: ReglaConteoMicrociclo) -> list[Violacion]:
    """Cuenta sesiones de la clase en cada microciclo: las sesiones concretas
    si está detallado (nivel 1), o sus objetivos si no (nivel 2)."""
    violaciones = []
    for micro, _ in _microciclos(plan):
        if micro.detallado:
            cantidad = sum(1 for s in micro.sesiones if s.clase_sesion == regla.clase_sesion)
        else:
            cantidad = micro.objetivos.sesiones_por_clase.get(regla.clase_sesion, 0)

        if regla.minimo is not None and cantidad < regla.minimo:
            limite = f"el mínimo es {regla.minimo}"
        elif regla.maximo is not None and cantidad > regla.maximo:
            limite = f"el máximo es {regla.maximo}"
        else:
            continue
        violaciones.append(
            Violacion(
                regla_id=regla.id,
                fecha=micro.fecha_inicio,
                mensaje=(
                    f"La semana del {micro.fecha_inicio} tiene {cantidad} sesiones de "
                    f"{regla.clase_sesion.value}; {limite}."
                ),
            )
        )
    return violaciones


def _secuencia_bloques(plan: Plan, secuencia: SecuenciaBloques) -> list[Violacion]:
    """Los mesociclos siguen la secuencia del perfil en orden: el plan puede
    usar solo los primeros bloques, pero no saltarse, reordenar ni añadir."""
    esperados = ", ".join(o.value for o in secuencia.objetivos)
    violaciones = []
    if len(plan.mesociclos) > len(secuencia.objetivos):
        violaciones.append(
            Violacion(
                regla_id=secuencia.id,
                fecha=plan.mesociclos[len(secuencia.objetivos)].fecha_inicio,
                mensaje=(
                    f"El plan tiene {len(plan.mesociclos)} mesociclos y la secuencia solo "
                    f"define {len(secuencia.objetivos)}: {esperados}."
                ),
            )
        )
    for posicion, (meso, esperado) in enumerate(zip(plan.mesociclos, secuencia.objetivos), start=1):
        if meso.objetivo != esperado:
            violaciones.append(
                Violacion(
                    regla_id=secuencia.id,
                    fecha=meso.fecha_inicio,
                    mensaje=(
                        f"El mesociclo {posicion} ({meso.fecha_inicio}) es {meso.objetivo.value}; "
                        f"según la secuencia debe ser {esperado.value} (orden: {esperados})."
                    ),
                )
            )
    return violaciones


def _tipos_semana(plan: Plan, tipos: TiposSemana) -> list[Violacion]:
    permitidos = ", ".join(t.value for t in tipos.tipos)
    return [
        Violacion(
            regla_id=tipos.id,
            fecha=micro.fecha_inicio,
            mensaje=(
                f"La semana del {micro.fecha_inicio} es de tipo {micro.tipo_microciclo.value}; "
                f"la metodología solo usa: {permitidos}."
            ),
        )
        for micro, _ in _microciclos(plan)
        if micro.tipo_microciclo not in tipos.tipos
    ]


# ---------- punto de entrada ----------

def validar_plan(
    plan: Plan, perfil: PerfilMetodologia, atleta: Optional[FichaAtleta] = None
) -> ResultadoValidacion:
    """Comprueba el plan contra todas las reglas de plan del perfil. Las
    reglas que dependen del atleta (solo_si) se evalúan con su ficha; si no se
    puede saber si aplican, quedan como no evaluables."""
    resultado = ResultadoValidacion()
    condiciones = condiciones_atleta(perfil, atleta)

    def aplica(regla_id: str, condicion: Optional[CondicionAtleta]) -> bool:
        """Si la regla se debe evaluar para este atleta. Si no aplica, se da
        por cumplida; si no se sabe, se reporta como no evaluable."""
        if condicion is None:
            return True
        cumple = condiciones[condicion]
        if cumple is None:
            resultado.reglas_no_evaluables.append(
                ReglaNoEvaluable(
                    regla_id=regla_id,
                    motivo=(
                        f"Solo aplica si el atleta está {condicion.value.replace('_', ' ')} y no se puede saber: "
                        "faltan sus umbrales aeróbico y de lactato (o el perfil no define deficiencia_aerobica_pct)."
                    ),
                )
            )
            return False
        if not cumple:
            resultado.reglas_evaluadas.append(regla_id)
        return cumple

    def registrar(regla_id: str, violaciones: list[Violacion]) -> None:
        resultado.reglas_evaluadas.append(regla_id)
        resultado.violaciones.extend(violaciones)

    def no_evaluable(regla_id: str, parametros: dict) -> None:
        claves = ", ".join(sorted(parametros)) or "(ninguno)"
        resultado.reglas_no_evaluables.append(
            ReglaNoEvaluable(
                regla_id=regla_id,
                motivo=f"El motor no sabe evaluar los parámetros: {claves}.",
            )
        )

    for regla in perfil.reglas:
        if not aplica(regla.id, regla.solo_si):
            continue
        evaluador = _EVALUADORES_REGLA.get(frozenset(regla.parametros))
        if evaluador is None:
            no_evaluable(regla.id, regla.parametros)
        else:
            registrar(regla.id, evaluador(plan, regla))

    for restriccion in perfil.restricciones_globales:
        evaluador = _EVALUADORES_RESTRICCION.get(frozenset(restriccion.parametros))
        if evaluador is None:
            no_evaluable(restriccion.id, restriccion.parametros)
        else:
            registrar(restriccion.id, evaluador(plan, restriccion))

    for regla in perfil.reglas_secuenciales:
        registrar(regla.id, _secuencial(plan, regla))

    for regla in perfil.reglas_conteo_microciclo:
        if aplica(regla.id, regla.solo_si):
            registrar(regla.id, _conteo(plan, regla))

    if perfil.tipos_semana is not None:
        registrar(perfil.tipos_semana.id, _tipos_semana(plan, perfil.tipos_semana))

    # Solo la secuencia del modo del plan; las de otros modos no aplican.
    secuencia = perfil.secuencia_para(plan.modo)
    if secuencia is not None:
        registrar(secuencia.id, _secuencia_bloques(plan, secuencia))

    return resultado
