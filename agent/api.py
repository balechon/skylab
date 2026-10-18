# API HTTP mínima de PB_coach. Publicada solo en 127.0.0.1 del host (en el
# VPS, por túnel SSH); contrato en docs/api.md.
#
#   GET  /health            sin autenticación (healthcheck)
#   POST /plan              crear un ciclo nuevo
#   GET  /atleta            ficha vigente del atleta
#   PUT  /atleta            guarda una versión nueva de la ficha
#   POST /semana/ajustar    ajuste semanal del plan vigente; cuerpo opcional con
#                           los comentarios del atleta; ?forzar=true para
#                           rehacer una semana ya ajustada
#
# Garmin es otro servicio (pb-coach-sync): el sync se llama antes y la
# publicación en el reloj después. Esta API no depende de MCP; trabaja con lo
# que ya está en Postgres.
#
# Todo salvo /health exige "Authorization: Bearer <PB_COACH_API_TOKEN>". Si el
# token no está configurado, la API se niega a operar en vez de quedar abierta.

import hmac
import os
from functools import lru_cache
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from agent import servicio
from agent.esquemas import ComentariosAtleta, SolicitudCiclo
from agent.llm import crear_modelo
from core.athlete import FichaAtleta
from persistence import repository as repo
from persistence.db import crear_engine, crear_sesiones

app = FastAPI(title="pb-coach")


# ---------- dependencias ----------

@lru_cache
def obtener_sesiones_db() -> sessionmaker:
    return crear_sesiones(crear_engine())


def obtener_modelo() -> BaseChatModel:
    # Proveedor y modelo según PB_COACH_MODELO (por defecto Claude Opus 5.5).
    return crear_modelo()


def exigir_token(authorization: Optional[str] = Header(default=None)) -> None:
    esperado = os.environ.get("PB_COACH_API_TOKEN")
    if not esperado:
        raise HTTPException(status_code=503, detail="PB_COACH_API_TOKEN no está configurado")
    recibido = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(recibido, esperado):
        raise HTTPException(status_code=401, detail="Token inválido")


# ---------- respuestas ----------

class RespuestaPlan(BaseModel):
    estado: str
    resumen: Optional[str] = None
    plan_id: Optional[int] = None
    version: Optional[int] = None
    accion: Optional[dict[str, Any]] = None
    justificaciones: list[dict[str, Any]] = []
    violaciones: list[dict[str, Any]] = []
    feedback: Optional[dict[str, Any]] = None
    detalle: str = ""
    tokens_entrada: int = 0
    tokens_salida: int = 0


def _respuesta(r: servicio.RespuestaServicio) -> RespuestaPlan:
    e = r.ejecucion
    resultado = e.resultado
    accion = r.evaluacion.accion if r.evaluacion and r.evaluacion.accion else None
    return RespuestaPlan(
        estado=resultado.estado.value if resultado else e.estado,
        resumen=resultado.resumen if resultado else None,
        plan_id=r.plan_id,
        version=r.version,
        accion=accion.model_dump(mode="json") if accion else None,
        justificaciones=[j.model_dump(mode="json") for j in resultado.justificaciones] if resultado else [],
        violaciones=[v.model_dump(mode="json") for v in resultado.violaciones] if resultado else [],
        feedback=resultado.feedback.model_dump(mode="json") if resultado and resultado.feedback else None,
        detalle=e.detalle,
        tokens_entrada=e.tokens_entrada,
        tokens_salida=e.tokens_salida,
    )


# ---------- endpoints ----------

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/plan", dependencies=[Depends(exigir_token)])
def crear_plan(
    solicitud: SolicitudCiclo,
    sesiones_db: sessionmaker = Depends(obtener_sesiones_db),
    modelo=Depends(obtener_modelo),
) -> RespuestaPlan:
    if not (servicio.perfiles_dir() / f"{solicitud.perfil}.yaml").exists():
        raise HTTPException(status_code=404, detail=f"No existe el perfil {solicitud.perfil}")
    try:
        return _respuesta(servicio.crear_ciclo(sesiones_db, modelo, solicitud))
    except servicio.PerfilIncompleto as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.post("/semana/ajustar", dependencies=[Depends(exigir_token)])
def ajustar_semana(
    comentarios: Optional[ComentariosAtleta] = None,
    forzar: bool = False,
    sesiones_db: sessionmaker = Depends(obtener_sesiones_db),
    modelo=Depends(obtener_modelo),
) -> RespuestaPlan:
    try:
        respuesta = servicio.ajuste_semanal(sesiones_db, modelo, forzar=forzar, comentarios=comentarios)
    except (servicio.SinPlanVigente, servicio.AjusteYaHecho) as error:
        raise HTTPException(status_code=409, detail=str(error))
    except servicio.PerfilIncompleto as error:
        raise HTTPException(status_code=422, detail=str(error))
    return _respuesta(respuesta)


@app.get("/atleta", dependencies=[Depends(exigir_token)])
def obtener_atleta(sesiones_db: sessionmaker = Depends(obtener_sesiones_db)) -> FichaAtleta:
    with sesiones_db() as db:
        ficha = repo.ficha_vigente(db)
    if ficha is None:
        raise HTTPException(status_code=404, detail="Todavía no hay ficha del atleta")
    return ficha


@app.put("/atleta", dependencies=[Depends(exigir_token)])
def guardar_atleta(ficha: FichaAtleta, sesiones_db: sessionmaker = Depends(obtener_sesiones_db)) -> FichaAtleta:
    # Cada PUT añade una versión: las ejecuciones guardan la copia con la que
    # planificaron, así que cambiar la ficha no reescribe el pasado.
    with sesiones_db.begin() as db:
        repo.guardar_ficha(db, ficha)
    return ficha
