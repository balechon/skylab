# Notion y SKYLAB falsos para probar el servicio sin red.

import itertools
from datetime import date
from typing import Any, Optional

from notion.clientes import RespuestaSkylab
from notion import propiedades as p


class NotionFalso:
    """Bases en memoria. Guarda las propiedades tal cual se escriben: el
    lector de `propiedades` entiende ese formato igual que el de la API."""

    def __init__(self):
        self.bases: dict[str, dict[str, dict[str, Any]]] = {}
        self.creadas: list[tuple[str, dict[str, Any]]] = []
        self.actualizadas: list[tuple[str, dict[str, Any]]] = []
        self._ids = itertools.count(1)

    def anadir(self, ds: str, propiedades: dict[str, Any]) -> str:
        page_id = f"pagina{next(self._ids):04d}"
        self.bases.setdefault(ds, {})[page_id] = {"id": page_id, "properties": dict(propiedades)}
        return page_id

    def filas(self, ds: str) -> list[dict[str, Any]]:
        return list(self.bases.get(ds, {}).values())

    def fila(self, ds: str, clave: str) -> Optional[dict[str, Any]]:
        return next((f for f in self.filas(ds) if p.leer(f, "Clave") == clave), None)

    async def consultar(self, data_source_id: str, filtro: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        return [dict(f, properties=dict(f["properties"])) for f in self.filas(data_source_id)]

    async def crear(self, data_source_id: str, propiedades: dict[str, Any]) -> dict[str, Any]:
        page_id = self.anadir(data_source_id, propiedades)
        self.creadas.append((data_source_id, propiedades))
        return {"id": page_id}

    async def actualizar(self, page_id: str, propiedades: dict[str, Any]) -> None:
        for base in self.bases.values():
            if page_id in base:
                base[page_id]["properties"].update(propiedades)
                self.actualizadas.append((page_id, propiedades))
                return
        raise KeyError(page_id)


class SkylabFalso:
    def __init__(self, plan: Optional[dict[str, Any]] = None, sesiones: Optional[list[dict[str, Any]]] = None,
                 atleta: Optional[dict[str, Any]] = None):
        self.plan_actual = plan
        self.sesiones_actuales = sesiones or []
        self.atleta_actual = atleta
        self.respuesta_ajuste = RespuestaSkylab(200, {"estado": "plan_valido", "version": 2, "feedback": None})
        self.llamadas: list[tuple[str, Any]] = []

    async def atleta(self) -> RespuestaSkylab:
        return RespuestaSkylab(200, self.atleta_actual) if self.atleta_actual else RespuestaSkylab(404, {"detail": "sin ficha"})

    async def guardar_atleta(self, ficha: dict[str, Any]) -> RespuestaSkylab:
        self.llamadas.append(("guardar_atleta", ficha))
        self.atleta_actual = ficha
        return RespuestaSkylab(200, ficha)

    async def plan(self) -> RespuestaSkylab:
        return RespuestaSkylab(200, self.plan_actual) if self.plan_actual else RespuestaSkylab(404, {"detail": "sin plan"})

    async def sesiones(self, desde: date, hasta: date) -> RespuestaSkylab:
        return RespuestaSkylab(200, [s for s in self.sesiones_actuales if desde.isoformat() <= s["fecha"] <= hasta.isoformat()])

    async def ajustar(self, comentarios: Optional[dict[str, Any]], forzar: bool) -> RespuestaSkylab:
        self.llamadas.append(("ajustar", {"comentarios": comentarios, "forzar": forzar}))
        return self.respuesta_ajuste

    async def sincronizar(self) -> RespuestaSkylab:
        self.llamadas.append(("sincronizar", None))
        return RespuestaSkylab(200, {"ok": True})

    async def publicar(self) -> RespuestaSkylab:
        self.llamadas.append(("publicar", None))
        return RespuestaSkylab(200, {"ok": True})

    def nombres(self) -> list[str]:
        return [n for n, _ in self.llamadas]
