# Conexión a Postgres. La URL llega por la variable de entorno DATABASE_URL
# (ver docker-compose.yml); nunca se escribe en el código.

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker


def crear_engine(url: str | None = None, **kwargs) -> Engine:
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Falta DATABASE_URL (postgresql+psycopg://usuario:clave@host:5432/base)")
    return create_engine(url, pool_pre_ping=True, **kwargs)


def crear_sesiones(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
