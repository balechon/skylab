# HTTP mínimo del servicio de sync. Solo accesible dentro de la red de Docker.
#
#   GET  /health  sin autenticación (healthcheck)
#   POST /sync    Garmin → Postgres; exige "Authorization: Bearer <PB_COACH_API_TOKEN>"
#
# Es un servicio aparte de la API para que MCP no conviva con FastAPI ni con
# el agente: si garmin-mcp falla o no está levantado, solo falla /sync, y la
# planificación sigue funcionando con los datos ya guardados.

import asyncio
import hmac
import logging
import os
from functools import lru_cache

from sqlalchemy.orm import sessionmaker
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from pb_coach.persistence.db import crear_engine, crear_sesiones
from pb_coach.sync.sincronizacion import sincronizar_ahora

log = logging.getLogger("pb_coach.sync")


@lru_cache
def sesiones_db() -> sessionmaker:
    return crear_sesiones(crear_engine())


def _error_de_token(request: Request) -> JSONResponse | None:
    esperado = os.environ.get("PB_COACH_API_TOKEN")
    if not esperado:
        return JSONResponse({"detail": "PB_COACH_API_TOKEN no está configurado"}, status_code=503)
    recibido = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(recibido, esperado):
        return JSONResponse({"detail": "Token inválido"}, status_code=401)
    return None


def causa_raiz(error: BaseException) -> BaseException:
    """El SDK de MCP envuelve los fallos de conexión en grupos de excepciones
    (con cancelaciones internas). Se busca el primer error real para
    devolverlo legible."""
    if isinstance(error, BaseExceptionGroup):
        reales = [e for e in error.exceptions if not isinstance(e, (asyncio.CancelledError, GeneratorExit))]
        return causa_raiz((reales or list(error.exceptions))[0])
    return error


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def sync(request: Request) -> JSONResponse:
    if (error := _error_de_token(request)) is not None:
        return error
    try:
        resultado = await request.app.state.sincronizar(request.app.state.sesiones_db())
    except (Exception, BaseExceptionGroup) as error:  # noqa: BLE001 — se devuelve a n8n
        log.exception("Falló el sync de Garmin")
        causa = causa_raiz(error)
        return JSONResponse({"ok": False, "error": f"{type(causa).__name__}: {causa}"}, status_code=502)
    return JSONResponse({"ok": True, "resultado": resultado.model_dump(mode="json")})


def crear_app(sincronizar=sincronizar_ahora, fabrica_sesiones=sesiones_db) -> Starlette:
    app = Starlette(routes=[Route("/health", health), Route("/sync", sync, methods=["POST"])])
    app.state.sincronizar = sincronizar
    app.state.sesiones_db = fabrica_sesiones
    return app


app = crear_app()
