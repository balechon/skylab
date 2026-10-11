# Sync completo: cliente Garmin falso → Postgres real (esquema temporal).

import asyncio
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from pb_coach.persistence import repository as repo
from pb_coach.sync.sincronizacion import DIAS_INICIALES, sincronizar
from tests.mcp_client.test_garmin import ClienteGarminFalso, resumen_garmin

HOY = date(2026, 10, 20)


@pytest.fixture
def sesiones_db(engine):
    fabrica = sessionmaker(bind=engine, expire_on_commit=False)
    yield fabrica
    with engine.begin() as conexion:
        conexion.execute(text("TRUNCATE sesion_realizada RESTART IDENTITY"))


def test_primer_sync_trae_la_linea_base_y_el_segundo_no_duplica(sesiones_db):
    cliente = ClienteGarminFalso(
        [
            resumen_garmin(1, inicio="2026-08-01 07:00:00"),  # fuera de la línea base de 56 días
            resumen_garmin(2, inicio="2026-09-10 07:00:00"),
            resumen_garmin(3, tipo="running", inicio="2026-10-15 18:00:00"),
        ]
    )
    primero = asyncio.run(sincronizar(sesiones_db, cliente, hoy=HOY))
    assert (HOY - primero.desde).days == DIAS_INICIALES
    assert (primero.traidas, primero.nuevas) == (2, 2)

    # Llega una actividad nueva; el sync arranca en la última fecha guardada.
    cliente.actividades.append(resumen_garmin(4, inicio="2026-10-19 07:00:00"))
    segundo = asyncio.run(sincronizar(sesiones_db, cliente, hoy=HOY))
    assert segundo.desde == date(2026, 10, 15)
    assert (segundo.traidas, segundo.nuevas) == (2, 1)

    with sesiones_db() as db:
        guardadas = repo.sesiones_entre(db, date(2026, 1, 1), HOY)
    assert [s.garmin_activity_id for s in guardadas] == [2, 3, 4]
