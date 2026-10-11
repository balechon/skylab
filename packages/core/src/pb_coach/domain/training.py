# Entidades de dominio del entrenamiento: sesiones (planificadas y
# realizadas), microciclos, mesociclos y el plan.
#
# Planificación rodante en tres niveles de detalle (ver docs/vision.md):
#   nivel 1 — Microciclo con sesiones concretas (la próxima semana)
#   nivel 2 — Microciclo solo con objetivos (resto del mesociclo actual)
#   nivel 3 — Mesociclo sin microciclos, solo esqueleto (bloques futuros)
#
# Aquí solo vive la integridad estructural de los datos (tipos, fechas,
# coherencia clase/tipo). Si una regla depende de la metodología, va en
# engine/, no aquí. Un validador nunca corrige el dato: solo lo rechaza.

from datetime import date, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Terreno(str, Enum):
    """Terreno de entrenamiento"""
    ASFALTO = "Asfalto"
    PISTA = "Pista"
    CAMINO_NO_TECNICO = "Camino no técnico"
    SENDERO_TECNICO = "Sendero técnico"
    ALTA_MONTANA = "Alta montaña"


class TipoSesion(str, Enum):
    """Tipo de sesión de entrenamiento running/trailrunning"""
    SERIES = "Series"
    TEMPO = "Tempo"
    UMBRAL = "Umbral"
    BASE = "Base"
    FONDO = "Fondo"
    FUERZA = "Fuerza"
    RECUPERACION = "Recuperación"


class ClaseSesion(str, Enum):
    """Clase de sesión de entrenamiento running/trailrunning"""
    FONDO = "Fondo"            # F — Z1,Z2 — Base, Fondo
    ESPECIFICO = "Específico"  # E — Z3-Z5 — Series, Tempo, Umbral
    RECUPERACION = "Recuperación"  # R — Z1 — Recuperación
    DESCANSO = "Descanso"      # D — NA — ninguno


class ZonasFC(str, Enum):
    """Zonas de frecuencia cardíaca"""
    Z1 = "Z1"
    Z2 = "Z2"
    Z3 = "Z3"
    Z4 = "Z4"
    Z5 = "Z5"


# que tipo de sesiones esta permitido en cada clase de sesión
TIPOS_PERMITIDOS: dict[ClaseSesion, set[TipoSesion]] = {
    ClaseSesion.FONDO: {TipoSesion.BASE, TipoSesion.FONDO, TipoSesion.RECUPERACION},
    ClaseSesion.ESPECIFICO: {TipoSesion.SERIES, TipoSesion.TEMPO, TipoSesion.UMBRAL, TipoSesion.FUERZA},
    ClaseSesion.RECUPERACION: {TipoSesion.RECUPERACION},
    ClaseSesion.DESCANSO: set(),
}


def _validar_tipo_para_clase(clase: ClaseSesion, tipo: Optional[TipoSesion]) -> None:
    """Rechaza un tipo_sesion que no corresponde a su clase_sesion."""
    if clase == ClaseSesion.DESCANSO:
        if tipo is not None:
            raise ValueError(
                f"Descanso pasivo no debe tener tipo_sesion, recibido: {tipo!r}"
            )
    elif tipo not in TIPOS_PERMITIDOS[clase]:
        raise ValueError(
            f"Tipo de sesión {tipo!r} no permitido para clase de sesión {clase}\n"
            f"validos: {TIPOS_PERMITIDOS[clase]}"
        )


def _validar_rango_fechas(inicio: date, fin: date) -> None:
    if fin < inicio:
        raise ValueError("fecha_fin debe ser posterior (o igual) a fecha_inicio")


def _validar_bloques_ordenados(bloques: list, nombre: str) -> None:
    """Los bloques hijos deben ir en orden cronológico y sin solaparse."""
    for anterior, siguiente in zip(bloques, bloques[1:]):
        if siguiente.fecha_inicio <= anterior.fecha_fin:
            raise ValueError(
                f"{nombre} {siguiente.fecha_inicio} - {siguiente.fecha_fin} se solapa "
                f"o va antes que {anterior.fecha_inicio} - {anterior.fecha_fin}"
            )


# ---------- Sesiones ----------

class SesionPlanificada(BaseModel):
    """Una sesión que el plan prescribe (nivel 1). Lo que se pide, no lo que
    se hizo — eso es SesionRealizada.

    Descanso pasivo es una sesión explícita (no un día ausente) para poder
    contar y comparar semanas de carga y de descarga.
    """

    fecha: date
    clase_sesion: ClaseSesion
    tipo_sesion: Optional[TipoSesion] = None
    terreno: Optional[Terreno] = None

    distancia_objetivo_km: Optional[float] = Field(default=None, gt=0)
    duracion_objetivo: Optional[timedelta] = None
    zona_fc_objetivo: Optional[ZonasFC] = None
    desnivel_positivo_objetivo_m: Optional[float] = Field(default=None, ge=0)
    descripcion: Optional[str] = None  # ej. "6x800 m a ritmo de 5K, rec. 2'"

    @model_validator(mode="after")
    def validar_coherencia(self) -> "SesionPlanificada":
        _validar_tipo_para_clase(self.clase_sesion, self.tipo_sesion)

        if self.duracion_objetivo is not None and self.duracion_objetivo <= timedelta(0):
            raise ValueError("duracion_objetivo debe ser positiva")

        if self.clase_sesion == ClaseSesion.DESCANSO:
            con_carga = [
                campo
                for campo in (
                    "terreno",
                    "distancia_objetivo_km",
                    "duracion_objetivo",
                    "zona_fc_objetivo",
                    "desnivel_positivo_objetivo_m",
                )
                if getattr(self, campo) is not None
            ]
            if con_carga:
                raise ValueError(f"Descanso pasivo no debe tener {con_carga}")
        elif self.distancia_objetivo_km is None and self.duracion_objetivo is None:
            raise ValueError(
                "Una sesión con carga necesita distancia_objetivo_km o duracion_objetivo"
            )
        return self


class SesionRealizada(BaseModel):
    """Una actividad que realmente ocurrió (llega de Garmin vía sync).

    clase_sesion/tipo_sesion son opcionales: Garmin no sabe si un rodaje fue
    Fondo o Recuperación. Esa clasificación la hace engine/, no este modelo.
    Se admite clase sin tipo para registros manuales. El descanso no se
    registra como actividad: es la ausencia de una.

    segundos_por_zona es el tiempo real en cada zona de FC. No se resume en
    una sola zona: en montaña el pulso sube en las subidas y baja en las
    bajadas, y una zona "predominante" falsearía la intensidad.
    """

    fecha: date
    duracion: timedelta
    distancia_km: float = Field(ge=0)
    terreno: Optional[Terreno] = None
    clase_sesion: Optional[ClaseSesion] = None
    tipo_sesion: Optional[TipoSesion] = None

    desnivel_positivo_m: Optional[float] = Field(default=None, ge=0)
    desnivel_negativo_m: Optional[float] = Field(default=None, ge=0)
    fc_media: Optional[int] = Field(default=None, gt=0)
    segundos_por_zona: dict[ZonasFC, float] = Field(default_factory=dict)
    ritmo_medio_min_km: Optional[float] = Field(default=None, gt=0)
    rpe: Optional[int] = Field(default=None, ge=1, le=10)
    sensaciones: Optional[str] = None

    # Carga de entrenamiento de Garmin (basada en EPOC). Fuente principal de
    # carga; si falta, engine/ usa sRPE (rpe x minutos) como respaldo.
    carga_epoc: Optional[float] = Field(default=None, ge=0)

    garmin_activity_id: Optional[int] = None

    @model_validator(mode="after")
    def validar_coherencia(self) -> "SesionRealizada":
        if self.duracion <= timedelta(0):
            raise ValueError("duracion de una sesión realizada debe ser positiva")
        negativos = {z: s for z, s in self.segundos_por_zona.items() if s < 0}
        if negativos:
            raise ValueError(f"segundos_por_zona no puede tener tiempos negativos: {negativos}")
        if self.clase_sesion == ClaseSesion.DESCANSO:
            raise ValueError(
                "Una sesión realizada no puede ser Descanso: el descanso es la ausencia de actividad"
            )
        if self.clase_sesion is not None:
            if self.tipo_sesion is not None:
                _validar_tipo_para_clase(self.clase_sesion, self.tipo_sesion)
        elif self.tipo_sesion is not None:
            raise ValueError("tipo_sesion requiere clase_sesion")
        return self


# ---------- Microciclo ----------

class TipoMicrociclo(str, Enum):
    CARGA = "Carga"
    DESCARGA = "Descarga"


class ObjetivosMicrociclo(BaseModel):
    """Lo que se espera de una semana (nivel 2), antes de bajarla a
    sesiones concretas. El volumen se puede fijar en tiempo, en distancia o
    en ambos (en trail, y en metodologías como Uphill Athlete, se planifica
    en horas)."""

    duracion: Optional[timedelta] = None
    volumen_km: Optional[float] = Field(default=None, ge=0)
    sesiones_por_clase: dict[ClaseSesion, int] = Field(default_factory=dict)
    desnivel_positivo_m: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validar_conteos(self) -> "ObjetivosMicrociclo":
        if self.duracion is None and self.volumen_km is None:
            raise ValueError("Los objetivos de la semana necesitan duracion, volumen_km o ambos")
        if self.duracion is not None and self.duracion < timedelta(0):
            raise ValueError("duracion no puede ser negativa")
        negativos = {c: n for c, n in self.sesiones_por_clase.items() if n < 0}
        if negativos:
            raise ValueError(f"sesiones_por_clase no puede tener conteos negativos: {negativos}")
        return self


class Microciclo(BaseModel):
    """Una semana del plan. Sin sesiones es nivel 2 (solo objetivos); con
    sesiones es nivel 1 (detallado)."""

    fecha_inicio: date
    fecha_fin: date
    tipo_microciclo: TipoMicrociclo
    objetivos: ObjetivosMicrociclo
    sesiones: list[SesionPlanificada] = Field(default_factory=list)

    @property
    def detallado(self) -> bool:
        return bool(self.sesiones)

    @model_validator(mode="after")
    def validar_coherencia(self) -> "Microciclo":
        _validar_rango_fechas(self.fecha_inicio, self.fecha_fin)
        for s in self.sesiones:
            if not (self.fecha_inicio <= s.fecha <= self.fecha_fin):
                raise ValueError(
                    f"Sesión {s.fecha} fuera del rango del microciclo {self.fecha_inicio} - {self.fecha_fin}"
                )
        return self


# ---------- Mesociclo ----------

class ObjetivoMesociclo(str, Enum):
    """Objetivo del mesociclo"""
    BASE_AEROBICA = "Base aeróbica"
    ACONDICIONAMIENTO_ESTRUCTURAL = "Acondicionamiento estructural"
    FUERZA_Y_ECONOMIA = "Fuerza y economía"
    ACONDICIONAMIENTO_EXCENTRICO = "Acondicionamiento excéntrico"
    UMBRAL = "Umbral"
    POTENCIA_AEROBICA = "Potencia aeróbica"
    VELOCIDAD_Y_POTENCIA = "Velocidad y potencia"
    ESPECIFICO_COMPETENCIA = "Específico competencia"
    PUESTA_A_PUNTO = "Puesta a punto"
    TRANSICION = "Transición"


class Mesociclo(BaseModel):
    """Un bloque con un objetivo de entrenamiento. Sin microciclos es nivel 3
    (esqueleto de un bloque futuro)."""

    objetivo: ObjetivoMesociclo
    fecha_inicio: date
    fecha_fin: date
    volumen_semanal_medio_km: Optional[float] = Field(default=None, ge=0)
    microciclos: list[Microciclo] = Field(default_factory=list)

    @model_validator(mode="after")
    def validar_coherencia(self) -> "Mesociclo":
        _validar_rango_fechas(self.fecha_inicio, self.fecha_fin)
        for m in self.microciclos:
            if not (self.fecha_inicio <= m.fecha_inicio <= m.fecha_fin <= self.fecha_fin):
                raise ValueError(
                    f"Microciclo {m.fecha_inicio} - {m.fecha_fin} fuera del rango del mesociclo {self.fecha_inicio} - {self.fecha_fin}"
                )
        _validar_bloques_ordenados(self.microciclos, "Microciclo")
        return self


# ---------- Plan ----------

class ModoPlan(str, Enum):
    """Construcción: progresar hacia adelante hasta una fecha de corte, sin
    carrera. Competición: planificar hacia atrás desde una carrera."""
    CONSTRUCCION = "Construcción"
    COMPETICION = "Competición"


class Carrera(BaseModel):
    nombre: str
    fecha: date
    distancia_km: float = Field(gt=0)
    desnivel_positivo_m: Optional[float] = Field(default=None, ge=0)


class Plan(BaseModel):
    """El plan completo. Cada ajuste semanal produce una versión nueva.

    fecha_objetivo es la fecha de corte en modo construcción y el día de la
    carrera en modo competición.
    """

    modo: ModoPlan
    fecha_inicio: date
    fecha_objetivo: date
    carrera: Optional[Carrera] = None
    version: int = Field(default=1, ge=1)
    mesociclos: list[Mesociclo] = Field(min_length=1)

    @model_validator(mode="after")
    def validar_coherencia(self) -> "Plan":
        if self.fecha_objetivo < self.fecha_inicio:
            raise ValueError("fecha_objetivo debe ser posterior (o igual) a fecha_inicio")

        if self.modo == ModoPlan.COMPETICION:
            if self.carrera is None:
                raise ValueError("Un plan en modo competición necesita una carrera")
            if self.carrera.fecha != self.fecha_objetivo:
                raise ValueError(
                    f"En modo competición fecha_objetivo ({self.fecha_objetivo}) "
                    f"debe ser la fecha de la carrera ({self.carrera.fecha})"
                )
        elif self.carrera is not None:
            raise ValueError("Un plan en modo construcción no tiene carrera")

        for m in self.mesociclos:
            if not (self.fecha_inicio <= m.fecha_inicio <= m.fecha_fin <= self.fecha_objetivo):
                raise ValueError(
                    f"Mesociclo {m.fecha_inicio} - {m.fecha_fin} fuera del rango del plan {self.fecha_inicio} - {self.fecha_objetivo}"
                )
        _validar_bloques_ordenados(self.mesociclos, "Mesociclo")
        return self
