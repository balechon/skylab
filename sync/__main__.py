# Sync manual:  docker compose exec pb-coach-sync python -m sync

import asyncio

from persistence.db import crear_engine, crear_sesiones
from sync.sincronizacion import sincronizar_ahora

resultado = asyncio.run(sincronizar_ahora(crear_sesiones(crear_engine())))
print(
    f"Sync {resultado.desde} → {resultado.hasta}: "
    f"{resultado.traidas} actividades de running, {resultado.nuevas} nuevas."
)
