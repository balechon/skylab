# Planes y contextos de prueba para el agente, construidos sobre el perfil
# didáctico. HOY es lunes: la semana que empieza hoy es la "próxima" y debe
# ir detallada.

from datetime import date, timedelta
from pathlib import Path

from agent.contexto import ContextoAgente, SolicitudCiclo
from agent.resultado import EstadoResultado, Justificacion, Operacion, ResultadoAgente
from core.training import (
    ClaseSesion,
    Mesociclo,
    Microciclo,
    ModoPlan,
    ObjetivoMesociclo,
    ObjetivosMicrociclo,
    Plan,
    SesionPlanificada,
    SesionRealizada,
    TipoMicrociclo,
    TipoSesion,
    ZonasFC,
)
from core.loader import cargar_perfil

HOY = date(2026, 10, 12)
FIN = date(2026, 12, 31)
PERFIL = cargar_perfil(Path(__file__).parents[2] / "methodology" / "profiles" / "ejemplo_didactico.yaml")


def _sesion(dia, clase, tipo=None, zona=None, inicio=HOY):
    fecha = inicio + timedelta(days=dia)
    if clase == ClaseSesion.DESCANSO:
        return SesionPlanificada(fecha=fecha, clase_sesion=clase)
    return SesionPlanificada(fecha=fecha, clase_sesion=clase, tipo_sesion=tipo, distancia_objetivo_km=8, zona_fc_objetivo=zona)


def semana_detallada(inicio=HOY):
    return [
        _sesion(0, ClaseSesion.DESCANSO, inicio=inicio),
        _sesion(1, ClaseSesion.ESPECIFICO, TipoSesion.SERIES, ZonasFC.Z4, inicio=inicio),
        _sesion(2, ClaseSesion.RECUPERACION, TipoSesion.RECUPERACION, ZonasFC.Z1, inicio=inicio),
        _sesion(3, ClaseSesion.FONDO, TipoSesion.BASE, ZonasFC.Z2, inicio=inicio),
        _sesion(4, ClaseSesion.DESCANSO, inicio=inicio),
    ]


def _micro(semana, km, tipo=TipoMicrociclo.CARGA, detallada=False, primera=HOY):
    inicio = primera + timedelta(weeks=semana)
    return Microciclo(
        fecha_inicio=inicio,
        fecha_fin=inicio + timedelta(days=6),
        tipo_microciclo=tipo,
        objetivos=ObjetivosMicrociclo(volumen_km=km, sesiones_por_clase={ClaseSesion.DESCANSO: 1, ClaseSesion.ESPECIFICO: 1}),
        sesiones=semana_detallada(inicio) if detallada else [],
    )


def plan_valido(version=1, primera=HOY, detallar=0) -> Plan:
    """Mesociclo de base de 4 semanas (40, 44, 48, descarga 30) y un
    esqueleto de fuerza hasta fin de año. `detallar` = semana con sesiones."""
    kms = [40, 44, 48, 30]
    micros = [
        _micro(i, km, TipoMicrociclo.DESCARGA if i == 3 else TipoMicrociclo.CARGA, detallada=(i == detallar), primera=primera)
        for i, km in enumerate(kms)
    ]
    base = Mesociclo(
        objetivo=ObjetivoMesociclo.BASE_AEROBICA,
        fecha_inicio=primera,
        fecha_fin=primera + timedelta(weeks=4, days=-1),
        microciclos=micros,
    )
    fuerza = Mesociclo(
        objetivo=ObjetivoMesociclo.FUERZA_Y_ECONOMIA,
        fecha_inicio=primera + timedelta(weeks=4),
        fecha_fin=FIN,
    )
    return Plan(modo=ModoPlan.CONSTRUCCION, fecha_inicio=primera, fecha_objetivo=FIN, version=version, mesociclos=[base, fuerza])


def resultado_valido(plan: Plan | None = None, regla_ids=("EJEMPLO-PROGRESION-001", "EJEMPLO-BLOQUES-001")) -> ResultadoAgente:
    return ResultadoAgente(
        estado=EstadoResultado.PLAN_VALIDO,
        plan=plan or plan_valido(),
        justificaciones=[Justificacion(decision="Progresión del 10% en base aeróbica.", regla_ids=list(regla_ids))],
        resumen="Semana de carga con una sesión de series.",
    )


def sesiones_realizadas() -> list[SesionRealizada]:
    return [
        SesionRealizada(fecha=HOY - timedelta(days=d), duracion=timedelta(minutes=50), distancia_km=8, carga_epoc=120)
        for d in (2, 4, 6, 9)
    ]


def contexto_ciclo(**cambios) -> ContextoAgente:
    datos = dict(
        operacion=Operacion.CREAR_CICLO,
        hoy=HOY,
        nombre_perfil="ejemplo_didactico",
        perfil=PERFIL,
        sesiones=sesiones_realizadas(),
        solicitud=SolicitudCiclo(modo=ModoPlan.CONSTRUCCION, perfil="ejemplo_didactico", fecha_objetivo=FIN),
    )
    datos.update(cambios)
    return ContextoAgente(**datos)
