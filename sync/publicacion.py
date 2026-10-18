# Publicar en Garmin (y de ahí al reloj) la próxima semana del plan vigente.
# Determinista, sin LLM: el agente decide el plan; esto solo lo traduce y
# lo envía.
#
#   1. toma el primer microciclo que no ha terminado (debe estar detallado);
#   2. si esas fechas ya tienen entrenamientos de otra versión del plan, los
#      retira (los quita del calendario y los borra de la biblioteca);
#   3. sube cada sesión con carga y la programa en su fecha.
#
# Cada escritura en Garmin se registra en Postgres justo después, para que
# un fallo a mitad de camino no deje la base desincronizada con la cuenta.
# Volver a publicar la misma versión no hace nada.

import logging
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import sessionmaker

from core.training import ClaseSesion, Microciclo, Plan
from persistence import repository as repo
from sync.entrenamientos import nombre_entrenamiento, sesion_a_entrenamiento
from sync.garmin import ClienteGarmin, ErrorGarmin

log = logging.getLogger("skylab.sync.publicacion")


class NadaQuePublicar(RuntimeError):
    pass


class EntrenamientoPublicado(BaseModel):
    fecha: date
    nombre: str
    garmin_workout_id: int


class ResultadoPublicacion(BaseModel):
    plan_id: int
    version: int
    semana: date
    publicados: list[EntrenamientoPublicado] = Field(default_factory=list)
    retirados: int = 0
    sin_cambios: bool = False
    avisos: list[str] = Field(default_factory=list)


def _proxima_semana(plan: Plan, hoy: date) -> Optional[Microciclo]:
    return next(
        (m for meso in plan.mesociclos for m in meso.microciclos if m.fecha_fin >= hoy),
        None,
    )


async def publicar_semana(
    sesiones_db: sessionmaker, cliente: ClienteGarmin, hoy: Optional[date] = None, forzar: bool = False
) -> ResultadoPublicacion:
    """Publica la próxima semana del plan vigente. Si esa versión ya está
    publicada no hace nada, salvo `forzar`: entonces retira lo publicado y lo
    vuelve a subir (p. ej. tras cambiar cómo se nombran los entrenamientos, o
    si el reloj quedó desincronizado)."""
    hoy = hoy or date.today()
    with sesiones_db() as db:
        vigente = repo.plan_vigente(db)
    if vigente is None:
        raise NadaQuePublicar("No hay un plan activo que publicar.")
    plan_id, plan = vigente

    semana = _proxima_semana(plan, hoy)
    if semana is None or not semana.detallado:
        raise NadaQuePublicar("La próxima semana del plan no tiene sesiones concretas (nivel 1).")

    sesiones = [s for s in semana.sesiones if s.fecha >= hoy and s.clase_sesion != ClaseSesion.DESCANSO]
    resultado = ResultadoPublicacion(plan_id=plan_id, version=plan.version, semana=semana.fecha_inicio)

    with sesiones_db() as db:
        # Las fechas pasadas no se tocan: ese entrenamiento ya se hizo (o no).
        previas = [p for p in repo.publicaciones_activas(db, hoy, semana.fecha_fin)]

    ya_publicadas = {p.fecha for p in previas if (p.plan_id, p.version) == (plan_id, plan.version)}
    if not forzar and previas and len(ya_publicadas) == len(previas) and ya_publicadas >= {s.fecha for s in sesiones}:
        resultado.sin_cambios = True
        return resultado

    if previas:
        programados = await cliente.programados_entre(min(p.fecha for p in previas), max(p.fecha for p in previas))
        for previa in previas:
            for entrada in programados:
                if entrada.get("workout_id") == previa.garmin_workout_id and entrada.get("scheduled_workout_id"):
                    await _tolerante(cliente.desprogramar(entrada["scheduled_workout_id"]), previa, resultado)
            await _tolerante(cliente.borrar_entrenamiento(previa.garmin_workout_id), previa, resultado)
            with sesiones_db.begin() as db:
                repo.marcar_retirada(db, previa.id)
            resultado.retirados += 1

    origen = f"SKYLAB p{plan_id} v{plan.version}"
    for sesion in sesiones:
        workout_id = await cliente.subir_entrenamiento(sesion_a_entrenamiento(sesion, origen, plan.rangos_fc))
        await cliente.programar(workout_id, sesion.fecha)
        nombre = nombre_entrenamiento(sesion)
        with sesiones_db.begin() as db:
            repo.registrar_publicacion(db, plan_id, plan.version, sesion.fecha, workout_id, nombre)
        resultado.publicados.append(EntrenamientoPublicado(fecha=sesion.fecha, nombre=nombre, garmin_workout_id=workout_id))
    return resultado


async def _tolerante(llamada, previa: repo.Publicacion, resultado: ResultadoPublicacion) -> None:
    """Retirar algo que ya no existe en Garmin (p. ej. lo borraste a mano) no
    debe bloquear la publicación: se avisa y se sigue."""
    try:
        await llamada
    except ErrorGarmin as error:
        log.warning("No se pudo retirar %s: %s", previa.nombre, error)
        resultado.avisos.append(f"{previa.nombre}: {error}")
