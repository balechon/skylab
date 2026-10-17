# Uso manual dentro del contenedor:
#   docker compose exec pb-coach-sync python -m sync            # Garmin → Postgres
#   docker compose exec pb-coach-sync python -m sync publicar   # próxima semana → reloj

import asyncio
import sys

from persistence.db import crear_engine, crear_sesiones
from sync.app import publicar_ahora
from sync.sincronizacion import sincronizar_ahora

sesiones_db = crear_sesiones(crear_engine())

if sys.argv[1:] == ["publicar"]:
    r = asyncio.run(publicar_ahora(sesiones_db))
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
