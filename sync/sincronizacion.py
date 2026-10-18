# Sincronización Garmin → Postgres. Determinista, sin LLM.
#
# Trae las actividades desde la última fecha guardada (incluida: ese día pudo
# haber más de una) hasta hoy y las guarda sin duplicar. La primera vez trae
# los últimos DIAS_INICIALES días como línea base.

import os
from datetime import date, timedelta
from typing import Optional

from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from sync.garmin import ClienteGarmin, traer_sesiones
from persistence import repository as repo

DIAS_INICIALES = 56

# El RPE anterior a esta fecha no se registraba con criterio: se ignora.
RPE_DESDE_POR_DEFECTO = date(2026, 10, 7)


class ResultadoSync(BaseModel):
    desde: date
    hasta: date
    traidas: int
    nuevas: int


def rpe_desde_configurado() -> date:
    valor = os.environ.get("GARMIN_RPE_DESDE")
    return date.fromisoformat(valor) if valor else RPE_DESDE_POR_DEFECTO


async def sincronizar(
    sesiones_db: sessionmaker,
    cliente: ClienteGarmin,
    hoy: Optional[date] = None,
    rpe_desde: Optional[date] = None,
) -> ResultadoSync:
    hoy = hoy or date.today()
    with sesiones_db() as db:
        ultima = repo.ultima_fecha_sincronizada(db)
    desde = ultima or hoy - timedelta(days=DIAS_INICIALES)

    sesiones = await traer_sesiones(cliente, desde, hoy, rpe_desde)

    with sesiones_db.begin() as db:
        nuevas = repo.guardar_sesiones(db, sesiones)
        repo.completar_limites_zonas(db, sesiones)
    return ResultadoSync(desde=desde, hasta=hoy, traidas=len(sesiones), nuevas=nuevas)


async def rellenar_limites_zonas(sesiones_db: sessionmaker, cliente: ClienteGarmin, desde: date, hasta: date) -> int:
    """Vuelve a leer de Garmin las actividades entre dos fechas y rellena los
    límites de zona de las ya guardadas que no los tienen."""
    sesiones = await traer_sesiones(cliente, desde, hasta)
    with sesiones_db.begin() as db:
        return repo.completar_limites_zonas(db, sesiones)


async def sincronizar_ahora(sesiones_db: sessionmaker) -> ResultadoSync:
    """Abre la sesión MCP con garmin-mcp y sincroniza hasta hoy."""
    async with ClienteGarmin() as cliente:
        return await sincronizar(sesiones_db, cliente, rpe_desde=rpe_desde_configurado())
