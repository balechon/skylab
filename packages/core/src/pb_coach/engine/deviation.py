# Cierre de semana: clasifica lo realizado, mide la adherencia frente a lo
# planificado y decide qué regla de ajuste del perfil se activa.
#
# Funciones puras, sin IO ni LLM. El motor decide la acción; el LLM solo la
# concreta después (ver docs/vision.md → Reglas de ajuste).

import operator
from datetime import timedelta
from statistics import mean
from typing import Optional

from pydantic import BaseModel, Field

from pb_coach.domain.methodology import (
    AccionAjuste,
    MetricaAjuste,
    OperadorComparacion,
    PerfilMetodologia,
    ReglaAjuste,
)
from pb_coach.domain.training import (
    ClaseSesion,
    Microciclo,
    SesionPlanificada,
    SesionRealizada,
)
from pb_coach.engine.calculator import ResumenPeriodo, resumir_periodo
from pb_coach.engine.validator import ReglaNoEvaluable

# Cuando se activan varias reglas, gana la acción más conservadora: ante
# señales de fatiga, proteger al atleta va antes que progresar.
PRIORIDAD_ACCIONES: list[AccionAjuste] = [
    AccionAjuste.REDUCIR_CARGA,
    AccionAjuste.ADELANTAR_DESCARGA,
    AccionAjuste.REPETIR_MICROCICLO,
    AccionAjuste.EXTENDER_MESOCICLO,
    AccionAjuste.MANTENER,
    AccionAjuste.PROGRESAR,
]

_OPERADORES = {
    OperadorComparacion.MENOR: operator.lt,
    OperadorComparacion.MENOR_O_IGUAL: operator.le,
    OperadorComparacion.MAYOR: operator.gt,
    OperadorComparacion.MAYOR_O_IGUAL: operator.ge,
}


class ReglaActivada(BaseModel):
    regla_id: str
    accion: AccionAjuste
    parametros: dict[str, float | int | str]
    metrica: MetricaAjuste
    valor_metrica: float
    umbral: str  # ej. "< 70"


class EvaluacionSemana(BaseModel):
    """Lo que el motor concluye al cerrar una semana."""

    resumen: ResumenPeriodo
    metricas: dict[MetricaAjuste, float]
    metricas_no_disponibles: list[MetricaAjuste]
    reglas_activadas: list[ReglaActivada] = Field(default_factory=list)
    reglas_no_evaluables: list[ReglaNoEvaluable] = Field(default_factory=list)
    accion: Optional[ReglaActivada] = None  # None: ninguna regla se activó, se sigue el plan


# ---------- clasificación ----------

def clasificar_sesiones(
    realizadas: list[SesionRealizada], planificadas: list[SesionPlanificada]
) -> list[SesionRealizada]:
    """Asigna clase y tipo a las sesiones sin clasificar emparejándolas con
    la sesión planificada con carga del mismo día (cada planificada se
    empareja con una sola realizada). Sin pareja, la sesión queda sin
    clasificar.

    No se clasifica por zona de FC: en montaña el pulso sube en las subidas
    aunque el esfuerzo sea de fondo, y en este atleta incluso la base cae en
    zonas altas, así que la zona confundiría Fondo con Específico.

    Las sesiones que ya traen clase no se tocan. Devuelve copias: la
    entrada no se modifica.
    """
    pendientes = [p for p in planificadas if p.clase_sesion != ClaseSesion.DESCANSO]
    resultado = []
    for sesion in realizadas:
        if sesion.clase_sesion is not None:
            resultado.append(sesion)
            continue

        pareja = next((p for p in pendientes if p.fecha == sesion.fecha), None)
        if pareja is None:
            resultado.append(sesion)
            continue
        pendientes.remove(pareja)
        resultado.append(
            sesion.model_copy(update={"clase_sesion": pareja.clase_sesion, "tipo_sesion": pareja.tipo_sesion})
        )
    return resultado


# ---------- métricas ----------

def _adherencia_volumen(microciclo: Microciclo, resumen: ResumenPeriodo) -> Optional[float]:
    """Realizado / planificado en %, en la unidad del objetivo de la semana
    (tiempo si lo tiene, si no km)."""
    objetivos = microciclo.objetivos
    if objetivos.duracion is not None:
        if objetivos.duracion == timedelta(0):
            return None
        return round(resumen.duracion / objetivos.duracion * 100, 1)
    if objetivos.volumen_km:
        return round(resumen.distancia_km / objetivos.volumen_km * 100, 1)
    return None


def _adherencia_sesiones(microciclo: Microciclo, realizadas: list[SesionRealizada]) -> Optional[float]:
    """Sesiones con carga cumplidas / previstas en %.

    En una semana detallada, una sesión prevista cuenta como cumplida si hay
    una actividad ese día. Si solo hay objetivos, se compara el número de
    actividades con el número de sesiones previstas (máximo 100%).
    """
    if microciclo.detallado:
        previstas = [s for s in microciclo.sesiones if s.clase_sesion != ClaseSesion.DESCANSO]
        if not previstas:
            return None
        dias_con_actividad = [s.fecha for s in realizadas]
        cumplidas = 0
        for prevista in previstas:
            if prevista.fecha in dias_con_actividad:
                dias_con_actividad.remove(prevista.fecha)
                cumplidas += 1
        return round(cumplidas / len(previstas) * 100, 1)

    previstas = sum(
        n for clase, n in microciclo.objetivos.sesiones_por_clase.items() if clase != ClaseSesion.DESCANSO
    )
    if previstas == 0:
        return None
    return round(min(len(realizadas), previstas) / previstas * 100, 1)


def calcular_metricas(
    microciclo: Microciclo, realizadas: list[SesionRealizada], resumen: ResumenPeriodo
) -> dict[MetricaAjuste, float]:
    """Métricas que se pueden calcular solo con la semana. Las de progreso
    (tests, indicadores pasivos) llegan desde fuera."""
    metricas: dict[MetricaAjuste, Optional[float]] = {
        MetricaAjuste.ADHERENCIA_VOLUMEN_PCT: _adherencia_volumen(microciclo, resumen),
        MetricaAjuste.ADHERENCIA_SESIONES_PCT: _adherencia_sesiones(microciclo, realizadas),
        MetricaAjuste.RPE_MEDIO: (
            round(mean(s.rpe for s in realizadas if s.rpe is not None), 1)
            if any(s.rpe is not None for s in realizadas)
            else None
        ),
    }
    return {m: v for m, v in metricas.items() if v is not None}


# ---------- reglas de ajuste ----------

def _se_activa(regla: ReglaAjuste, valor: float) -> bool:
    return _OPERADORES[regla.condicion.operador](valor, regla.condicion.valor)


def elegir_accion(activadas: list[ReglaActivada]) -> Optional[ReglaActivada]:
    """La regla activada con la acción más conservadora según
    PRIORIDAD_ACCIONES. Ante empate, la primera del perfil."""
    if not activadas:
        return None
    return min(activadas, key=lambda r: PRIORIDAD_ACCIONES.index(r.accion))


def evaluar_semana(
    microciclo: Microciclo,
    realizadas: list[SesionRealizada],
    perfil: PerfilMetodologia,
    metricas_externas: Optional[dict[MetricaAjuste, float]] = None,
) -> EvaluacionSemana:
    """Cierra una semana: clasifica, mide y decide la acción de ajuste.

    `metricas_externas` aporta las métricas de progreso que no salen de la
    propia semana (ej. mejora_test_pct al cerrar un mesociclo). Una regla
    cuya métrica no está disponible no se activa ni se da por descartada:
    queda en reglas_no_evaluables.
    """
    de_la_semana = [
        s for s in realizadas if microciclo.fecha_inicio <= s.fecha <= microciclo.fecha_fin
    ]
    clasificadas = clasificar_sesiones(de_la_semana, microciclo.sesiones)
    resumen = resumir_periodo(clasificadas, microciclo.fecha_inicio, microciclo.fecha_fin)

    metricas = calcular_metricas(microciclo, clasificadas, resumen)
    metricas.update(metricas_externas or {})

    activadas: list[ReglaActivada] = []
    no_evaluables: list[ReglaNoEvaluable] = []
    for regla in perfil.reglas_ajuste:
        metrica = regla.condicion.metrica
        if metrica not in metricas:
            no_evaluables.append(
                ReglaNoEvaluable(regla_id=regla.id, motivo=f"Métrica no disponible esta semana: {metrica.value}.")
            )
            continue
        if _se_activa(regla, metricas[metrica]):
            activadas.append(
                ReglaActivada(
                    regla_id=regla.id,
                    accion=regla.accion,
                    parametros=regla.parametros,
                    metrica=metrica,
                    valor_metrica=metricas[metrica],
                    umbral=f"{regla.condicion.operador.value} {regla.condicion.valor:g}",
                )
            )

    return EvaluacionSemana(
        resumen=resumen,
        metricas=metricas,
        metricas_no_disponibles=[m for m in MetricaAjuste if m not in metricas],
        reglas_activadas=activadas,
        reglas_no_evaluables=no_evaluables,
        accion=elegir_accion(activadas),
    )
