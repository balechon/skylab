# Entorno de Alembic: conecta con DATABASE_URL y compara contra los modelos
# de pb_coach.persistence.models.

from logging.config import fileConfig

from alembic import context

from pb_coach.persistence.db import crear_engine
from pb_coach.persistence.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Genera el SQL sin conectarse (alembic upgrade head --sql)."""
    import os

    context.configure(
        url=os.environ["DATABASE_URL"],
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Si quien llama ya trae una conexión (p. ej. los tests), se usa esa.
    conexion = config.attributes.get("connection")
    if conexion is not None:
        context.configure(connection=conexion, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = crear_engine()
    with engine.connect() as conexion:
        context.configure(connection=conexion, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
