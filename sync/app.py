# HTTP mínimo del servicio de sync. Solo accesible dentro de la red de Docker.
#
#   GET  /health     sin autenticación (healthcheck)
#   POST /sync       Garmin → Postgres
#   POST /publicar   próxima semana del plan vigente → Garmin (y al reloj)
#
# /sync y /publicar exigen "Authorization: Bearer <PB_COACH_API_TOKEN>".
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

from persistence.db import crear_engine, crear_sesiones
from sync.garmin import ClienteGarmin
from sync.publicacion import NadaQuePublicar, publicar_semana
from sync.sincronizacion import sincronizar_ahora

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


async def publicar_ahora(sesiones_db: sessionmaker):
    """Abre la sesión MCP con garmin-mcp y publica la próxima semana."""
    async with ClienteGarmin() as cliente:
        return await publicar_semana(sesiones_db, cliente)


async def _ejecutar(request: Request, operacion, nombre: str) -> JSONResponse:
    if (error := _error_de_token(request)) is not None:
        return error
    try:
        resultado = await operacion(request.app.state.sesiones_db())
    except NadaQuePublicar as error:
        return JSONResponse({"ok": False, "error": str(error)}, status_code=409)
    except (Exception, BaseExceptionGroup) as error:  # noqa: BLE001 — se devuelve al llamante
        log.exception("Falló %s", nombre)
        causa = causa_raiz(error)
        return JSONResponse({"ok": False, "error": f"{type(causa).__name__}: {causa}"}, status_code=502)
    return JSONResponse({"ok": True, "resultado": resultado.model_dump(mode="json")})


async def sync(request: Request) -> JSONResponse:
    return await _ejecutar(request, request.app.state.sincronizar, "el sync de Garmin")


async def publicar(request: Request) -> JSONResponse:
    return await _ejecutar(request, request.app.state.publicar, "la publicación en Garmin")


def crear_app(sincronizar=sincronizar_ahora, publicar_semana=publicar_ahora, fabrica_sesiones=sesiones_db) -> Starlette:
    app = Starlette(
        routes=[
            Route("/health", health),
            Route("/sync", sync, methods=["POST"]),
            Route("/publicar", publicar, methods=["POST"]),
        ]
    )
    app.state.sincronizar = sincronizar
    app.state.publicar = publicar_semana
    app.state.sesiones_db = fabrica_sesiones
    return app


app = crear_app()
