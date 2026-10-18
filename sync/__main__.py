# Uso manual dentro del contenedor:
#   docker compose exec skylab-sync python -m sync            # Garmin → Postgres
#   docker compose exec skylab-sync python -m sync publicar   # próxima semana → reloj
#   docker compose exec skylab-sync python -m sync publicar --forzar   # volver a subirla
#   docker compose exec skylab-sync python -m sync rellenar-zonas 2026-08-01
#       # rellena los límites de zona de las actividades ya guardadas

import asyncio
import sys
from datetime import date

from persistence.db import crear_engine, crear_sesiones
from sync.app import publicar_ahora
from sync.garmin import ClienteGarmin
from sync.sincronizacion import rellenar_limites_zonas, sincronizar_ahora

sesiones_db = crear_sesiones(crear_engine())

async def _rellenar(desde: date) -> int:
    async with ClienteGarmin() as cliente:
        return await rellenar_limites_zonas(sesiones_db, cliente, desde, date.today())


if sys.argv[1:2] == ["rellenar-zonas"] and len(sys.argv) == 3:
    print(f"Límites de zona completados: {asyncio.run(_rellenar(date.fromisoformat(sys.argv[2])))} actividades.")
elif sys.argv[1:2] == ["publicar"]:
    r = asyncio.run(publicar_ahora(sesiones_db, forzar="--forzar" in sys.argv[2:]))
    if r.sin_cambios:
        print(f"Plan {r.plan_id} v{r.version}: la semana del {r.semana} ya estaba publicada.")
    else:
        print(f"Plan {r.plan_id} v{r.version}, semana del {r.semana}: {len(r.publicados)} publicados, {r.retirados} retirados.")
        for p in r.publicados:
            print(f"  {p.fecha}  {p.nombre}  (workout {p.garmin_workout_id})")
    for aviso in r.avisos:
        print(f"  aviso: {aviso}")
else:
    r = asyncio.run(sincronizar_ahora(sesiones_db))
    print(f"Sync {r.desde} → {r.hasta}: {r.traidas} actividades de running, {r.nuevas} nuevas.")
