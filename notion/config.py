# Configuración del servicio, desde el entorno. El token de Notion se lee de
# un archivo (secreto de Docker), nunca de una variable de entorno: así no
# aparece en `docker inspect` ni en los logs.

import os
from dataclasses import dataclass
from pathlib import Path


class ConfiguracionIncompleta(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    ds_atleta: str
    ds_semanas: str
    ds_entrenamientos: str
    api_url: str
    sync_url: str
    api_token: str
    token_archivo: Path
    intervalo_segundos: int = 180
    simulacion: bool = False


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        raise ConfiguracionIncompleta(f"Falta la variable de entorno {nombre}")
    return valor


def desde_entorno() -> Config:
    return Config(
        ds_atleta=_requerida("NOTION_DS_ATLETA"),
        ds_semanas=_requerida("NOTION_DS_SEMANAS"),
        ds_entrenamientos=_requerida("NOTION_DS_ENTRENAMIENTOS"),
        api_url=os.environ.get("SKYLAB_API_URL", "http://skylab-api:8000"),
        sync_url=os.environ.get("SKYLAB_SYNC_URL", "http://skylab-sync:8000"),
        api_token=_requerida("SKYLAB_API_TOKEN"),
        token_archivo=Path(os.environ.get("NOTION_TOKEN_FILE", "/run/secrets/notion_token")),
        intervalo_segundos=int(os.environ.get("NOTION_INTERVALO_SEGUNDOS", "180")),
        simulacion=os.environ.get("NOTION_SIMULACION", "").lower() in ("1", "true", "si", "sí"),
    )


def leer_token(ruta: Path) -> str:
    """El token de la conexión interna de Notion. Se trata como un texto
    opaco: no se valida su formato (Notion pide no hacerlo)."""
    if not ruta.exists():
        raise ConfiguracionIncompleta(f"No existe el archivo del token de Notion: {ruta}")
    token = ruta.read_text(encoding="utf-8").strip()
    if not token:
        raise ConfiguracionIncompleta(f"El archivo del token de Notion está vacío: {ruta}")
    return token
