# Carga y valida un perfil de metodología YAML contra el modelo tipado en
# domain/methodology.py.

from pathlib import Path

import yaml

from pb_coach.domain.methodology import PerfilMetodologia


def cargar_perfil(ruta: Path | str) -> PerfilMetodologia:
    """Carga y valida un perfil de metodología desde un archivo YAML.

    Lanza FileNotFoundError si la ruta no existe, yaml.YAMLError si el
    archivo no es YAML válido, y pydantic.ValidationError si el contenido no
    cumple el esquema de PerfilMetodologia (incluidos IDs de regla
    duplicados). Nunca devuelve un perfil a medio construir.
    """
    with open(ruta, "r", encoding="utf-8") as archivo:
        contenido = yaml.safe_load(archivo)
    return PerfilMetodologia.model_validate(contenido)
