# Fixtures de base de datos para los tests que corren contra Postgres real.
#
# Cada ejecución crea un esquema temporal, aplica las migraciones de Alembic
# en él y lo borra al terminar: nunca toca las tablas reales. `db` corre cada
# test dentro de una transacción que se deshace al final.

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

URL = os.environ.get("TEST_DATABASE_URL")
ALEMBIC_INI = Path(__file__).parents[2] / "persistence" / "alembic.ini"


@pytest.fixture(scope="session")
def engine():
    if not URL:
        pytest.skip("TEST_DATABASE_URL no definida")
    esquema = f"test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(URL)
    with admin.begin() as conexion:
        conexion.execute(text(f'CREATE SCHEMA "{esquema}"'))

    engine = create_engine(URL, connect_args={"options": f"-csearch_path={esquema}"})
    config = Config(str(ALEMBIC_INI))
    with engine.begin() as conexion:
        config.attributes["connection"] = conexion
        command.upgrade(config, "head")

    yield engine

    engine.dispose()
    with admin.begin() as conexion:
        conexion.execute(text(f'DROP SCHEMA "{esquema}" CASCADE'))
    admin.dispose()


@pytest.fixture
def db(engine):
    conexion = engine.connect()
    transaccion = conexion.begin()
    sesion = Session(bind=conexion, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield sesion
    sesion.close()
    transaccion.rollback()
    conexion.close()
