# Sync manual:  docker compose exec pb-coach-sync python -m pb_coach.sync

import asyncio

from pb_coach.persistence.db import crear_engine, crear_sesiones
from pb_coach.sync.sincronizacion import sincronizar_ahora

resultado = asyncio.run(sincronizar_ahora(crear_sesiones(crear_engine())))
print(
    f"Sync {resultado.desde} → {resultado.hasta}: "
    f"{resultado.traidas} actividades de running, {resultado.nuevas} nuevas."
)
