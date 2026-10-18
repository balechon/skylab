# Ficha del atleta: los datos que decide o mide el atleta (no la
# metodología). La metodología vive en los perfiles YAML; la ficha llega por
# la API (PUT /atleta) y se guarda con cada ejecución del agente, para saber
# con qué datos se planificó. Ver docs/entradas.md.
#
# revisar_disponibilidad es una comprobación dura: la guardia rechaza un plan
# que ponga sesiones en días libres o más largas de lo que el atleta puede.

from datetime import date, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from core.methodology import AnclaZona, DefinicionZonas, LimiteZona
from core.training import ClaseSesion, Plan, RangoFC, ZonasFC


class DiaSemana(str, Enum):
    LUNES = "lunes"
    MARTES = "martes"
    MIERCOLES = "miércoles"
    JUEVES = "jueves"
    VIERNES = "viernes"
    SABADO = "sábado"
    DOMINGO = "domingo"

    @classmethod
    def de_fecha(cls, fecha: date) -> "DiaSemana":
        return list(cls)[fecha.weekday()]


class Umbrales(BaseModel):
    """Umbrales de FC del atleta, en pulsaciones por minuto."""

    fc_aerobico: Optional[int] = Field(default=None, ge=60, le=230)  # AeT
    metodo_aerobico: Optional[str] = None  # p. ej. "MAF (180 − edad)", "lactato"
    fc_lactato: Optional[int] = Field(default=None, ge=60, le=230)  # LT
    fc_maxima: Optional[int] = Field(default=None, ge=60, le=230)
    fc_reposo: Optional[int] = Field(default=None, ge=25, le=120)
    fecha: Optional[date] = None  # cuándo se midieron

    @model_validator(mode="after")
    def validar_orden(self) -> "Umbrales":
        orden = [self.fc_reposo, self.fc_aerobico, self.fc_lactato, self.fc_maxima]
        conocidos = [v for v in orden if v is not None]
        if conocidos != sorted(conocidos) or len(set(conocidos)) != len(conocidos):
            raise ValueError("Los umbrales deben cumplir reposo < aeróbico < lactato < máxima")
        return self


class Disponibilidad(BaseModel):
    """Cuánto puede entrenar el atleta cada día.

    Cada día admite como mucho `duracion_max_dia`, salvo los `dias_largos`
    (p. ej. sábado y domingo), de los que hasta `dias_largos_por_semana`
    pueden llegar a `duracion_max_dia_largo` (None: sin límite, el día
    completo). Así se expresa "el sábado o el domingo, uno de los dos, para
    la salida larga"."""

    duracion_max_dia: timedelta
    dias_sin_entrenar: list[DiaSemana] = Field(default_factory=list)
    dias_largos: list[DiaSemana] = Field(default_factory=list)
    dias_largos_por_semana: int = Field(default=0, ge=0, le=7)
    duracion_max_dia_largo: Optional[timedelta] = None

    @model_validator(mode="after")
    def validar_dias(self) -> "Disponibilidad":
        if set(self.dias_sin_entrenar) & set(self.dias_largos):
            raise ValueError("Un día no puede ser a la vez libre y día largo")
        if self.dias_largos_por_semana > len(self.dias_largos):
            raise ValueError("dias_largos_por_semana no puede superar el número de dias_largos")
        return self


class FichaAtleta(BaseModel):
    edad: int = Field(ge=10, le=100)
    categoria: Optional[str] = None  # según la metodología activa (p. ej. "1" en Uphill Athlete)
    umbrales: Umbrales = Field(default_factory=Umbrales)
    disponibilidad: Optional[Disponibilidad] = None
    lesiones: Optional[str] = Field(default=None, max_length=1000)  # historial y zonas delicadas
    notas: Optional[str] = Field(default=None, max_length=1000)


def _duracion_por_dia(plan: Plan, desde: date) -> tuple[dict[date, timedelta], list[date]]:
    """Duración planificada por día y fechas de sesiones sin duración."""
    totales: dict[date, timedelta] = {}
    sin_duracion: list[date] = []
    for meso in plan.mesociclos:
        for micro in meso.microciclos:
            for sesion in micro.sesiones:
                if sesion.fecha < desde or sesion.clase_sesion == ClaseSesion.DESCANSO:
                    continue
                if sesion.duracion_objetivo is None:
                    sin_duracion.append(sesion.fecha)
                    continue
                totales[sesion.fecha] = totales.get(sesion.fecha, timedelta()) + sesion.duracion_objetivo
    return totales, sin_duracion


def _hhmm(duracion: timedelta) -> str:
    minutos = int(duracion.total_seconds() // 60)
    return f"{minutos // 60}:{minutos % 60:02d}"


def revisar_disponibilidad(plan: Plan, disponibilidad: Disponibilidad, desde: date) -> list[str]:
    """Problemas de disponibilidad en las sesiones desde `desde` (las semanas
    pasadas ya no se pueden cambiar). Vacía si el plan cabe."""
    totales, sin_duracion = _duracion_por_dia(plan, desde)
    # Sin duración no se puede saber si la sesión cabe en el día.
    problemas = [
        f"La sesión del {fecha} no tiene duracion_objetivo: hace falta para comprobar la disponibilidad."
        for fecha in sin_duracion
    ]
    largos_por_semana: dict[date, list[date]] = {}
    for fecha, total in sorted(totales.items()):
        dia = DiaSemana.de_fecha(fecha)
        if dia in disponibilidad.dias_sin_entrenar:
            problemas.append(f"El {dia.value} {fecha} el atleta no puede entrenar y el plan pone sesión.")
            continue
        if total <= disponibilidad.duracion_max_dia:
            continue
        if dia not in disponibilidad.dias_largos:
            problemas.append(
                f"El {dia.value} {fecha} suma {_hhmm(total)} y el atleta puede como mucho "
                f"{_hhmm(disponibilidad.duracion_max_dia)}."
            )
            continue
        tope = disponibilidad.duracion_max_dia_largo
        if tope is not None and total > tope:
            problemas.append(
                f"El {dia.value} {fecha} suma {_hhmm(total)} y en un día largo puede como mucho {_hhmm(tope)}."
            )
        largos_por_semana.setdefault(fecha - timedelta(days=fecha.weekday()), []).append(fecha)

    for lunes, fechas in largos_por_semana.items():
        if len(fechas) > disponibilidad.dias_largos_por_semana:
            dias = ", ".join(f"{DiaSemana.de_fecha(f).value} {f}" for f in fechas)
            problemas.append(
                f"La semana del {lunes} tiene {len(fechas)} días de más de "
                f"{_hhmm(disponibilidad.duracion_max_dia)} ({dias}); el atleta solo puede "
                f"{disponibilidad.dias_largos_por_semana} por semana."
            )
    return problemas


def _valor_ancla(umbrales: Umbrales, ancla: AnclaZona) -> Optional[int]:
    return {
        AnclaZona.UMBRAL_AEROBICO: umbrales.fc_aerobico,
        AnclaZona.UMBRAL_LACTATO: umbrales.fc_lactato,
        AnclaZona.FC_MAXIMA: umbrales.fc_maxima,
    }[ancla]


def _pulsaciones(limite: LimiteZona, umbrales: Umbrales) -> Optional[int]:
    base = _valor_ancla(umbrales, limite.ancla)
    return None if base is None else round(base * (1 + limite.pct / 100))


def rangos_fc(definicion: Optional[DefinicionZonas], umbrales: Umbrales) -> dict[ZonasFC, RangoFC]:
    """Pulsaciones de cada zona para este atleta. Solo las zonas cuyos dos
    límites se pueden calcular con los umbrales conocidos (sin el umbral de
    lactato no hay Z3 ni Z4)."""
    if definicion is None:
        return {}
    rangos = {}
    for zona, limites in definicion.zonas.items():
        minimo, maximo = _pulsaciones(limites.desde, umbrales), _pulsaciones(limites.hasta, umbrales)
        if minimo is not None and maximo is not None and minimo < maximo:
            rangos[zona] = RangoFC(minimo=minimo, maximo=maximo)
    return rangos
