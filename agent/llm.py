# Fábrica del modelo de lenguaje. El agente no depende de un proveedor: el
# modelo se elige con SKYLAB_MODELO ("proveedor:modelo", el formato de
# init_chat_model de LangChain), p. ej. "anthropic:claude-opus-5-5" u
# "openai:...". Cambiar de proveedor es cambiar esa variable (e instalar su
# paquete langchain-<proveedor>).
#
# Lo específico de un proveedor vive solo aquí, en OPCIONES_PROVEEDOR; el
# resto del agente no sabe con qué modelo habla.

import os
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

MODELO_POR_DEFECTO = "anthropic:claude-opus-5-5"
MAX_TOKENS = 16000

OPCIONES_PROVEEDOR: dict[str, dict[str, Any]] = {
    "anthropic": {
        # Si un clasificador de seguridad rechaza la petición, la API la
        # reintenta en el modelo de respaldo que corresponda.
        "betas": ["server-side-fallback-2026-07-01"],
        "output_config": {"effort": "high"},
        "model_kwargs": {"fallbacks": "default"},
    },
}


def nombre_modelo() -> str:
    return os.environ.get("SKYLAB_MODELO", MODELO_POR_DEFECTO)


def proveedor(nombre: str) -> str:
    return nombre.split(":", 1)[0]


def crear_modelo(nombre: str | None = None) -> BaseChatModel:
    nombre = nombre or nombre_modelo()
    return init_chat_model(nombre, max_tokens=MAX_TOKENS, **OPCIONES_PROVEEDOR.get(proveedor(nombre), {}))


def mensaje_sistema(texto: str, nombre: str) -> SystemMessage:
    """El system es estable entre turnos: en Anthropic se marca para la caché
    del prompt; en otros proveedores va como texto plano."""
    if proveedor(nombre) == "anthropic":
        return SystemMessage(content=[{"type": "text", "text": texto, "cache_control": {"type": "ephemeral"}}])
    return SystemMessage(content=texto)
