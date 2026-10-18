# Cliente MCP de garmin-mcp (Taxuspt/garmin_mcp), que corre como contenedor
# propio en la red interna del docker-compose.
#
# Uso determinista (sin LLM) y con lista blanca: aunque el servidor expone
# más de 150 tools, este cliente solo puede llamar a TOOLS_PERMITIDAS. Las de
# escritura solo las usa la publicación de la semana (sync/publicacion.py),
# nunca el agente.
#
# La traducción de una actividad de Garmin a SesionRealizada es una función
# pura (actividad_a_sesion), separada del transporte para poder probarla sin
# red.

import json
import os
from contextlib import AsyncExitStack
from datetime import date, timedelta
from typing import Any, Optional

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from pydantic import BaseModel

from core.training import SesionRealizada, Terreno, ZonasFC

TOOLS_PERMITIDAS = frozenset(
    {
        # lectura
        "get_activities_by_date",
        "get_activity",
        "get_activity_hr_in_timezones",
        "get_scheduled_workouts",
        # escritura (publicar la semana en el reloj)
        "upload_workout",
        "schedule_workout",
        "unschedule_workout",
        "delete_workout",
    }
)

# Solo running. En trail Garmin no distingue el tipo de terreno (camino,
# sendero técnico, alta montaña), así que se deja vacío: cuenta el desnivel.
TERRENO_POR_TIPO: dict[str, Optional[Terreno]] = {
    "running": Terreno.ASFALTO,
    "track_running": Terreno.PISTA,
    "treadmill_running": None,
    "trail_running": None,
}

# "¿Cómo te sentiste?" de Garmin (0–100, en pasos de 25).
_SENSACIONES = {0: "Muy débil", 25: "Débil", 50: "Normal", 75: "Fuerte", 100: "Muy fuerte"}


class ErrorGarmin(RuntimeError):
    pass


# ---------- traducción pura ----------

def _rpe(valor: Any) -> Optional[int]:
    """Garmin guarda el esfuerzo percibido x10 (30 = RPE 3)."""
    if not valor:
        return None
    return min(10, max(1, round(float(valor) / 10)))


def _sensaciones(valor: Any) -> Optional[str]:
    if valor is None:
        return None
    return _SENSACIONES[min(_SENSACIONES, key=lambda k: abs(k - float(valor)))]


def _segundos_por_zona(zonas: list[dict[str, Any]]) -> dict[ZonasFC, float]:
    resultado = {}
    for zona in zonas:
        numero, segundos = zona.get("zoneNumber"), zona.get("secsInZone")
        if numero in range(1, 6) and segundos:
            resultado[ZonasFC(f"Z{numero}")] = round(float(segundos), 1)
    return resultado


def _limites_zonas(zonas: list[dict[str, Any]]) -> list[int]:
    """Suelo de cada zona (Z1..Z5) con el que el reloj calculó el tiempo
    por zona; vacío si Garmin no lo da completo."""
    suelos = {z.get("zoneNumber"): z.get("zoneLowBoundary") for z in zonas}
    if any(suelos.get(n) is None for n in range(1, 6)):
        return []
    return [int(suelos[n]) for n in range(1, 6)]


class ActividadCruda(BaseModel):
    """Una actividad tal como la devolvió Garmin (capa bronze)."""

    garmin_activity_id: int
    fecha: date
    resumen: dict[str, Any]
    detalle: dict[str, Any]
    zonas: list[Any]


def actividad_a_sesion(
    resumen: dict[str, Any],
    detalle: dict[str, Any],
    zonas: list[dict[str, Any]],
    rpe_desde: Optional[date] = None,
) -> Optional[SesionRealizada]:
    """Convierte una actividad de Garmin en SesionRealizada, o None si no es
    de running.

    `rpe_desde`: el RPE de actividades anteriores a esa fecha se ignora
    (antes no se registraba con criterio y contaminaría el sRPE).
    """
    if resumen.get("type") not in TERRENO_POR_TIPO:
        return None

    fecha = date.fromisoformat(str(resumen["start_time"])[:10])
    segundos = float(resumen["duration_seconds"])
    distancia_km = round(float(resumen.get("distance_meters") or 0) / 1000, 3)
    rpe_valido = rpe_desde is None or fecha >= rpe_desde

    return SesionRealizada(
        garmin_activity_id=int(resumen["id"]),
        fecha=fecha,
        duracion=timedelta(seconds=round(segundos)),
        distancia_km=distancia_km,
        terreno=TERRENO_POR_TIPO[resumen["type"]],
        desnivel_positivo_m=resumen.get("elevation_gain_meters"),
        desnivel_negativo_m=resumen.get("elevation_loss_meters"),
        fc_media=round(resumen["avg_hr_bpm"]) if resumen.get("avg_hr_bpm") else None,
        segundos_por_zona=_segundos_por_zona(zonas),
        limites_zonas=_limites_zonas(zonas),
        ritmo_medio_min_km=round(segundos / 60 / distancia_km, 2) if distancia_km > 0 else None,
        rpe=_rpe(detalle.get("workout_rpe")) if rpe_valido else None,
        sensaciones=_sensaciones(detalle.get("workout_feel")) if rpe_valido else None,
        carga_epoc=round(float(detalle["training_load"]), 1) if detalle.get("training_load") is not None else None,
    )


# ---------- transporte MCP ----------

class ClienteGarmin:
    """Sesión MCP con garmin-mcp. Usar como `async with ClienteGarmin() as g:`."""

    def __init__(self, url: Optional[str] = None):
        self.url = url or os.environ.get("GARMIN_MCP_URL", "http://garmin-mcp:8000/mcp")
        self._pila: Optional[AsyncExitStack] = None
        self._sesion: Optional[ClientSession] = None

    async def __aenter__(self) -> "ClienteGarmin":
        self._pila = AsyncExitStack()
        try:
            lectura, escritura = await self._pila.enter_async_context(streamable_http_client(self.url))
            self._sesion = await self._pila.enter_async_context(ClientSession(lectura, escritura))
            await self._sesion.initialize()
        except BaseException:
            # Si garmin-mcp no responde, se cierra aquí lo que se llegó a abrir
            # (en la misma tarea) en vez de dejar la conexión a medias.
            await self._pila.aclose()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        await self._pila.aclose()

    async def _llamar(self, tool: str, argumentos: dict[str, Any]) -> Any:
        if tool not in TOOLS_PERMITIDAS:
            raise ErrorGarmin(f"Tool no permitida: {tool}")
        resultado = await self._sesion.call_tool(tool, argumentos)
        texto = resultado.content[0].text if resultado.content else ""
        if resultado.is_error:
            raise ErrorGarmin(f"{tool} falló: {texto[:300]}")
        return _interpretar(tool, texto)

    async def actividades_entre(self, desde: date, hasta: date) -> list[dict[str, Any]]:
        # garmin-mcp numera las páginas desde 0 (pedir la 1 primero se salta
        # la primera página entera).
        actividades, pagina = [], 0
        while True:
            respuesta = await self._llamar(
                "get_activities_by_date",
                {"start_date": desde.isoformat(), "end_date": hasta.isoformat(), "page": pagina},
            )
            actividades.extend(respuesta.get("activities", []))
            if not respuesta.get("has_more"):
                return actividades
            pagina += 1

    async def detalle(self, activity_id: int) -> dict[str, Any]:
        return await self._llamar("get_activity", {"activity_id": activity_id})

    async def zonas_fc(self, activity_id: int) -> list[dict[str, Any]]:
        return await self._llamar("get_activity_hr_in_timezones", {"activity_id": activity_id})

    async def subir_entrenamiento(self, entrenamiento: dict[str, Any]) -> int:
        """Crea el entrenamiento en la biblioteca de Garmin; devuelve su id."""
        respuesta = await self._llamar("upload_workout", {"workout_data": entrenamiento})
        if not respuesta.get("workout_id"):
            raise ErrorGarmin(f"upload_workout no devolvió workout_id: {respuesta}")
        return int(respuesta["workout_id"])

    async def programar(self, workout_id: int, fecha: date) -> None:
        """Pone el entrenamiento en el calendario (y de ahí al reloj). Idempotente."""
        await self._llamar("schedule_workout", {"workout_id": workout_id, "calendar_date": fecha.isoformat()})

    async def programados_entre(self, desde: date, hasta: date) -> list[dict[str, Any]]:
        respuesta = await self._llamar(
            "get_scheduled_workouts", {"start_date": desde.isoformat(), "end_date": hasta.isoformat()}
        )
        return respuesta.get("scheduled_workouts", []) if isinstance(respuesta, dict) else []

    async def desprogramar(self, scheduled_workout_id: int) -> None:
        await self._llamar("unschedule_workout", {"scheduled_workout_id": scheduled_workout_id})

    async def borrar_entrenamiento(self, workout_id: int) -> None:
        await self._llamar("delete_workout", {"workout_id": workout_id})


def _interpretar(tool: str, texto: str) -> Any:
    """garmin-mcp no marca sus errores como errores MCP: los devuelve como
    texto ("Error uploading workout: ...") o como JSON con status "failed".
    Aquí se convierten en ErrorGarmin para que nunca pasen por un éxito."""
    if tool == "get_scheduled_workouts" and texto.startswith("No workouts scheduled"):
        return {"scheduled_workouts": []}
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        raise ErrorGarmin(f"{tool} falló: {texto[:300]}") from None
    if isinstance(datos, dict) and datos.get("status") == "failed":
        raise ErrorGarmin(f"{tool} falló: {datos.get('message', datos)}")
    return datos


async def traer_sesiones(
    cliente: ClienteGarmin,
    desde: date,
    hasta: date,
    rpe_desde: Optional[date] = None,
    crudas: Optional[list[ActividadCruda]] = None,
) -> list[SesionRealizada]:
    """Actividades de running entre dos fechas, ya convertidas. Pide el
    detalle y las zonas solo de las actividades de running. Si se pasa
    `crudas`, añade ahí lo que devolvió Garmin tal cual (capa bronze)."""
    sesiones = []
    for resumen in await cliente.actividades_entre(desde, hasta):
        if resumen.get("type") not in TERRENO_POR_TIPO:
            continue
        detalle = await cliente.detalle(resumen["id"])
        zonas = await cliente.zonas_fc(resumen["id"])
        sesion = actividad_a_sesion(resumen, detalle, zonas, rpe_desde)
        if sesion is not None:
            sesiones.append(sesion)
            if crudas is not None:
                crudas.append(ActividadCruda(garmin_activity_id=sesion.garmin_activity_id, fecha=sesion.fecha,
                                             resumen=resumen, detalle=detalle, zonas=zonas))
    return sesiones
