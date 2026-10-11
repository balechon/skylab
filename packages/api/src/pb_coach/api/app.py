# API HTTP mínima que n8n invoca (solo accesible dentro de la red de Docker).
#
#   GET  /health            sin autenticación (healthcheck)
#   POST /plan              crear un ciclo nuevo
#   POST /semana/ajustar    ajuste semanal del plan vigente
#
# El sync de Garmin es otro servicio (pb-coach-sync): n8n lo llama antes.
# Esta API no depende de MCP; trabaja con lo que ya está en Postgres.
#
# Todo salvo /health exige "Authorization: Bearer <PB_COACH_API_TOKEN>". Si el
# token no está configurado, la API se niega a operar en vez de quedar abierta.

import hmac
import os
from functools import lru_cache
from typing import Any, Optional

import anthropic
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from pb_coach.agent import servicio
from pb_coach.agent.contexto import SolicitudCiclo
from pb_coach.persistence.db import crear_engine, crear_sesiones

app = FastAPI(title="pb-coach")


# ---------- dependencias ----------

@lru_cache
def obtener_sesiones_db() -> sessionmaker:
    return crear_sesiones(crear_engine())


def obtener_cliente_llm() -> anthropic.Anthropic:
    return anthropic.Anthropic()


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
    cliente=Depends(obtener_cliente_llm),
) -> RespuestaPlan:
    if not (servicio.perfiles_dir() / f"{solicitud.perfil}.yaml").exists():
        raise HTTPException(status_code=404, detail=f"No existe el perfil {solicitud.perfil}")
    return _respuesta(servicio.crear_ciclo(sesiones_db, cliente, solicitud))


@app.post("/semana/ajustar", dependencies=[Depends(exigir_token)])
def ajustar_semana(
    sesiones_db: sessionmaker = Depends(obtener_sesiones_db),
    cliente=Depends(obtener_cliente_llm),
) -> RespuestaPlan:
    try:
        respuesta = servicio.ajuste_semanal(sesiones_db, cliente)
    except servicio.SinPlanVigente as error:
        raise HTTPException(status_code=409, detail=str(error))
    return _respuesta(respuesta)
