# Modelo tipado de un perfil de metodología (carga desde YAML, ver
# methodology/profiles/_template.yaml).

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from pb_coach.domain.training import ClaseSesion, ObjetivoMesociclo, TipoSesion


class CategoriaRegla(str, Enum):
    """Clasificación de una RegistroRegla — metadata, no afecta su evaluación."""

    CARGA = "Carga"
    PROGRESION = "Progresión"
    DESCANSO = "Descanso"
    INTENSIDAD = "Intensidad"


class RegistroRegla(BaseModel):
    """Una regla de metodología transcrita de la fuente del autor.

    Las condiciones de aplicabilidad (objetivo_mesociclo, clase_sesion,
    tipo_sesion) son todas opcionales: si quedan en None, la regla se
    interpreta como "aplica siempre, sin condición".
    """

    id: str
    categoria: CategoriaRegla
    descripcion: str

    objetivo_mesociclo: Optional[ObjetivoMesociclo] = None
    clase_sesion: Optional[ClaseSesion] = None
    tipo_sesion: Optional[TipoSesion] = None

    parametros: dict[str, float | int | str] = Field(default_factory=dict)


class RestriccionGlobal(BaseModel):
    """Una regla cuyo alcance es el Plan completo, no una sesión/mesociclo
    puntual (ej. "no más de 3 microciclos de carga seguidos sin descarga").
    """

    id: str
    descripcion: str
    parametros: dict[str, float | int | str] = Field(default_factory=dict)


class RegistroReglaSecuencial(BaseModel):
    """Regla sobre la relación entre una sesión y la sesión inmediatamente
    anterior dentro de un microciclo.

    clases_permitidas_despues es una lista de permitidas (no de prohibidas):
    dice explícitamente qué SÍ puede seguir a clase_sesion_previa, en vez de
    enumerar todo lo que no. Cualquier ClaseSesion ausente de la lista queda
    prohibida después de clase_sesion_previa.
    """

    id: str
    descripcion: str
    clase_sesion_previa: ClaseSesion
    clases_permitidas_despues: list[ClaseSesion] = Field(min_length=1)


class ReglaConteoMicrociclo(BaseModel):
    """Regla sobre cuántas sesiones de una clase dada debe/puede haber
    dentro de un microciclo (ej. "mínimo un día de Descanso por semana").
    """

    id: str
    descripcion: str
    clase_sesion: ClaseSesion
    minimo: Optional[int] = None
    maximo: Optional[int] = None

    @model_validator(mode="after")
    def validar_algun_limite_presente(self) -> "ReglaConteoMicrociclo":
        if self.minimo is None and self.maximo is None:
            raise ValueError(
                "ReglaConteoMicrociclo debe especificar minimo, maximo, o ambos"
            )
        if self.minimo is not None and self.maximo is not None and self.minimo > self.maximo:
            raise ValueError(
                f"minimo ({self.minimo}) no puede ser mayor que maximo ({self.maximo})"
            )
        return self


class MetricaAjuste(str, Enum):
    """Métricas que engine/ sabe calcular al cerrar una semana o un bloque.
    Lista cerrada: una regla no puede depender de algo que el motor no mide."""

    ADHERENCIA_VOLUMEN_PCT = "adherencia_volumen_pct"
    ADHERENCIA_SESIONES_PCT = "adherencia_sesiones_pct"
    RPE_MEDIO = "rpe_medio"
    MEJORA_TEST_PCT = "mejora_test_pct"
    MEJORA_INDICADOR_PASIVO_PCT = "mejora_indicador_pasivo_pct"


class OperadorComparacion(str, Enum):
    MENOR = "<"
    MENOR_O_IGUAL = "<="
    MAYOR = ">"
    MAYOR_O_IGUAL = ">="


class CondicionAjuste(BaseModel):
    metrica: MetricaAjuste
    operador: OperadorComparacion
    valor: float


class AccionAjuste(str, Enum):
    """Reacciones posibles a lo que pasó. Lista cerrada: el motor decide cuál
    aplica y el LLM solo la concreta; nunca inventa una fuera de aquí."""

    PROGRESAR = "progresar"
    MANTENER = "mantener"
    REDUCIR_CARGA = "reducir_carga"
    REPETIR_MICROCICLO = "repetir_microciclo"
    ADELANTAR_DESCARGA = "adelantar_descarga"
    EXTENDER_MESOCICLO = "extender_mesociclo"


class OrigenRegla(str, Enum):
    """autor: tal cual la fuente. propio: interpretación numérica propia de
    una indicación cualitativa del autor."""

    AUTOR = "autor"
    PROPIO = "propio"


class ReglaAjuste(BaseModel):
    """Cómo reaccionar a lo ocurrido: condición sobre una métrica → acción.

    Los umbrales y los cambios de carga se expresan en porcentajes relativos
    a la línea base del atleta (ej. parametros: {cambio_carga_pct: 5}).
    """

    id: str
    descripcion: str
    condicion: CondicionAjuste
    accion: AccionAjuste
    parametros: dict[str, float | int | str] = Field(default_factory=dict)
    origen: OrigenRegla


class PerfilMetodologia(BaseModel):
    """Un perfil de metodología completo — la traducción íntegra de un YAML
    de autor a objetos tipados. Solo un perfil está activo por Plan.
    """

    autor: str
    fuente: str
    version: str
    deportes_soportados: list[str]

    reglas: list[RegistroRegla] = Field(min_length=1)
    restricciones_globales: list[RestriccionGlobal] = Field(default_factory=list)
    reglas_secuenciales: list[RegistroReglaSecuencial] = Field(default_factory=list)
    reglas_conteo_microciclo: list[ReglaConteoMicrociclo] = Field(default_factory=list)
    reglas_ajuste: list[ReglaAjuste] = Field(default_factory=list)

    @model_validator(mode="after")
    def validar_ids_unicos(self) -> "PerfilMetodologia":
        todos_los_ids = (
            [r.id for r in self.reglas]
            + [r.id for r in self.restricciones_globales]
            + [r.id for r in self.reglas_secuenciales]
            + [r.id for r in self.reglas_conteo_microciclo]
            + [r.id for r in self.reglas_ajuste]
        )
        vistos: set[str] = set()
        duplicados: set[str] = set()
        for rid in todos_los_ids:
            if rid in vistos:
                duplicados.add(rid)
            vistos.add(rid)

        if duplicados:
            raise ValueError(f"IDs de regla duplicados en el perfil: {sorted(duplicados)}")
        return self
