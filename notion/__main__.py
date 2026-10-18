# Uso dentro del contenedor:
#   python -m notion                 # bucle: un ciclo cada NOTION_INTERVALO_SEGUNDOS (180)
#   python -m notion --una-vez       # un solo ciclo
#   python -m notion --simulacion    # lee Notion y la API, pero no escribe ni llama al modelo
#
# Un error en un ciclo se registra y el bucle sigue: Notion o la API pueden
# no responder un rato sin que el servicio se caiga.

import asyncio
import logging
import sys

from notion.clientes import ClienteNotion, ClienteSkylab, NotionEnSimulacion, SkylabEnSimulacion
from notion.config import desde_entorno, leer_token
from notion.servicio import ServicioNotion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("skylab.notion")


def crear_servicio(simulacion: bool) -> ServicioNotion:
    cfg = desde_entorno()
    notion = ClienteNotion(leer_token(cfg.token_archivo))
    skylab = ClienteSkylab(cfg.api_url, cfg.sync_url, cfg.api_token)
    if simulacion or cfg.simulacion:
        log.info("Modo simulación: no se escribe en Notion ni se llama al modelo.")
        notion, skylab = NotionEnSimulacion(notion), SkylabEnSimulacion(skylab)
    return ServicioNotion(notion, skylab, cfg.ds_atleta, cfg.ds_semanas, cfg.ds_entrenamientos)


async def un_ciclo(servicio: ServicioNotion) -> None:
    resumen = await servicio.ciclo()
    log.info(
        "Ciclo: ficha enviada=%s, peticiones=%s, filas creadas=%d, actualizadas=%d, avisos=%s",
        resumen.ficha_enviada, resumen.peticiones, resumen.filas_creadas, resumen.filas_actualizadas, resumen.avisos,
    )


async def bucle(servicio: ServicioNotion, intervalo: int) -> None:
    while True:
        try:
            await un_ciclo(servicio)
        except Exception:  # noqa: BLE001 — el servicio no se cae por un ciclo fallido
            log.exception("Falló el ciclo; se reintenta en %d s", intervalo)
        await asyncio.sleep(intervalo)


def main() -> None:
    argumentos = set(sys.argv[1:])
    servicio = crear_servicio(simulacion="--simulacion" in argumentos)
    if "--una-vez" in argumentos or "--simulacion" in argumentos:
        asyncio.run(un_ciclo(servicio))
    else:
        asyncio.run(bucle(servicio, desde_entorno().intervalo_segundos))


if __name__ == "__main__":
    main()
