# Cómo se llama cada sesión al entrenar, con la jerga habitual del running.
# Lo comparten el reloj (sync) y Notion, para que una sesión se llame igual
# en todas partes.

from core.training import SesionPlanificada, TipoSesion

ETIQUETA_TIPO = {
    TipoSesion.SERIES: "Series",
    TipoSesion.TEMPO: "Tempo",
    TipoSesion.UMBRAL: "Umbral",
    TipoSesion.BASE: "Base",
    TipoSesion.FONDO: "Fondo",
    TipoSesion.FUERZA: "Fuerza",
    TipoSesion.RECUPERACION: "Regenerativo",
    TipoSesion.SPRINTS_CUESTA: "Hill sprints",
    TipoSesion.ACELERACIONES: "Strides",
}


def etiqueta_sesion(sesion: SesionPlanificada) -> str:
    if sesion.tipo_sesion is not None:
        return ETIQUETA_TIPO[sesion.tipo_sesion]
    return sesion.clase_sesion.value
