# Los dos clientes del servicio: Notion (API oficial, versión 2025-09-03, con
# data sources) y SKYLAB (skylab-api y skylab-sync por la red interna).
#
# Cada uno tiene una versión "en simulación" que lee de verdad pero no
# escribe nada: registra lo que haría. Sirve para la primera puesta en marcha
# y para comprobar qué haría el servicio sin tocar Notion ni gastar llamadas
# al modelo.

import logging
from datetime import date
from typing import Any, Optional

import httpx
from notion_client import AsyncClient

log = logging.getLogger("skylab.notion")

VERSION_NOTION = "2025-09-03"


class ClienteNotion:
    def __init__(self, token: str):
        # El SDK reintenta los 429/529 respetando Retry-After.
        self._cliente = AsyncClient(auth=token, notion_version=VERSION_NOTION)

    async def consultar(self, data_source_id: str, filtro: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        paginas: list[dict[str, Any]] = []
        cursor = None
        while True:
            argumentos: dict[str, Any] = {"data_source_id": data_source_id, "page_size": 100}
            if filtro:
                argumentos["filter"] = filtro
            if cursor:
                argumentos["start_cursor"] = cursor
            respuesta = await self._cliente.data_sources.query(**argumentos)
            paginas += respuesta["results"]
            if not respuesta.get("has_more"):
                return paginas
            cursor = respuesta["next_cursor"]

    async def crear(self, data_source_id: str, propiedades: dict[str, Any]) -> dict[str, Any]:
        return await self._cliente.pages.create(
            parent={"type": "data_source_id", "data_source_id": data_source_id}, properties=propiedades
        )

    async def actualizar(self, page_id: str, propiedades: dict[str, Any]) -> None:
        await self._cliente.pages.update(page_id=page_id, properties=propiedades)


class NotionEnSimulacion:
    """Lee de Notion de verdad; las escrituras solo se registran."""

    def __init__(self, real: ClienteNotion):
        self._real = real
        self.escrituras: list[tuple[str, str, list[str]]] = []
        self._siguiente = 0

    async def consultar(self, data_source_id: str, filtro: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        return await self._real.consultar(data_source_id, filtro)

    async def crear(self, data_source_id: str, propiedades: dict[str, Any]) -> dict[str, Any]:
        self._siguiente += 1
        self.escrituras.append(("crear", data_source_id, sorted(propiedades)))
        log.info("[simulación] crearía una página en %s: %s", data_source_id, sorted(propiedades))
        return {"id": f"simulada{self._siguiente}", "properties": propiedades}

    async def actualizar(self, page_id: str, propiedades: dict[str, Any]) -> None:
        self.escrituras.append(("actualizar", page_id, sorted(propiedades)))
        log.info("[simulación] actualizaría %s: %s", page_id, sorted(propiedades))


class RespuestaSkylab:
    def __init__(self, codigo: int, cuerpo: Any):
        self.codigo = codigo
        self.cuerpo = cuerpo

    @property
    def ok(self) -> bool:
        return 200 <= self.codigo < 300

    @property
    def detalle(self) -> str:
        if isinstance(self.cuerpo, dict):
            return str(self.cuerpo.get("detail") or self.cuerpo.get("error") or self.cuerpo)
        return str(self.cuerpo)


class ClienteSkylab:
    # El ajuste semanal llama al modelo: puede tardar varios minutos.
    TIEMPO_AJUSTE = 1800

    def __init__(self, api_url: str, sync_url: str, token: str):
        self._api = api_url.rstrip("/")
        self._sync = sync_url.rstrip("/")
        self._cabeceras = {"Authorization": f"Bearer {token}"}

    async def _pedir(self, metodo: str, url: str, tiempo: float = 60, **kwargs) -> RespuestaSkylab:
        async with httpx.AsyncClient(timeout=tiempo, headers=self._cabeceras) as http:
            respuesta = await http.request(metodo, url, **kwargs)
        try:
            cuerpo = respuesta.json()
        except ValueError:
            cuerpo = respuesta.text
        return RespuestaSkylab(respuesta.status_code, cuerpo)

    async def atleta(self) -> RespuestaSkylab:
        return await self._pedir("GET", f"{self._api}/atleta")

    async def guardar_atleta(self, ficha: dict[str, Any]) -> RespuestaSkylab:
        return await self._pedir("PUT", f"{self._api}/atleta", json=ficha)

    async def plan(self) -> RespuestaSkylab:
        return await self._pedir("GET", f"{self._api}/plan")

    async def sesiones(self, desde: date, hasta: date) -> RespuestaSkylab:
        return await self._pedir("GET", f"{self._api}/sesiones", params={"desde": desde.isoformat(), "hasta": hasta.isoformat()})

    async def ajustar(self, comentarios: Optional[dict[str, Any]], forzar: bool) -> RespuestaSkylab:
        return await self._pedir(
            "POST",
            f"{self._api}/semana/ajustar",
            tiempo=self.TIEMPO_AJUSTE,
            params={"forzar": "true"} if forzar else None,
            json=comentarios,
        )

    async def sincronizar(self) -> RespuestaSkylab:
        return await self._pedir("POST", f"{self._sync}/sync", tiempo=600)

    async def publicar(self) -> RespuestaSkylab:
        return await self._pedir("POST", f"{self._sync}/publicar", tiempo=600)


class SkylabEnSimulacion:
    """Lee de la API de verdad; lo que escribe o cuesta dinero (guardar la
    ficha, ajustar con el modelo, sincronizar, publicar) solo se registra."""

    def __init__(self, real: ClienteSkylab):
        self._real = real
        self.escrituras: list[str] = []

    async def atleta(self) -> RespuestaSkylab:
        return await self._real.atleta()

    async def plan(self) -> RespuestaSkylab:
        return await self._real.plan()

    async def sesiones(self, desde: date, hasta: date) -> RespuestaSkylab:
        return await self._real.sesiones(desde, hasta)

    async def guardar_atleta(self, ficha: dict[str, Any]) -> RespuestaSkylab:
        return self._registrar("guardar la ficha del atleta")

    async def ajustar(self, comentarios: Optional[dict[str, Any]], forzar: bool) -> RespuestaSkylab:
        return self._registrar(f"lanzar el ajuste semanal (forzar={forzar}) con comentarios {comentarios}")

    async def sincronizar(self) -> RespuestaSkylab:
        return self._registrar("sincronizar Garmin")

    async def publicar(self) -> RespuestaSkylab:
        return self._registrar("publicar la semana en el reloj")

    def _registrar(self, accion: str) -> RespuestaSkylab:
        self.escrituras.append(accion)
        log.info("[simulación] %s", accion)
        return RespuestaSkylab(299, {"simulacion": accion})
