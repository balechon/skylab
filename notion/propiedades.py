# Propiedades de las páginas de Notion: cómo se escriben (lo que se envía a
# la API) y cómo se leen (lo que devuelve). `valor` entiende los dos
# formatos, así se puede comparar lo que hay con lo que se quiere escribir y
# no tocar Notion si no cambia nada.

from datetime import date
from typing import Any, Optional

_MAX_TEXTO = 2000  # caracteres por fragmento de texto en la API de Notion


def _fragmentos(texto: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": texto[i : i + _MAX_TEXTO]}} for i in range(0, len(texto), _MAX_TEXTO)]


def titulo(texto: str) -> dict[str, Any]:
    return {"title": _fragmentos(texto)}


def texto(contenido: Optional[str]) -> dict[str, Any]:
    return {"rich_text": _fragmentos(contenido) if contenido else []}


def numero(valor: Optional[float]) -> dict[str, Any]:
    return {"number": valor}


def seleccion(nombre: Optional[str]) -> dict[str, Any]:
    return {"select": {"name": nombre} if nombre else None}


def multiple(nombres: list[str]) -> dict[str, Any]:
    return {"multi_select": [{"name": n} for n in nombres]}


def fecha(dia: Optional[date]) -> dict[str, Any]:
    return {"date": {"start": dia.isoformat()} if dia else None}


def casilla(marcada: bool) -> dict[str, Any]:
    return {"checkbox": marcada}


def relacion(ids: list[str]) -> dict[str, Any]:
    return {"relation": [{"id": i} for i in ids]}


def _texto_plano(fragmentos: list[dict[str, Any]]) -> str:
    return "".join(f.get("plain_text") or f.get("text", {}).get("content", "") for f in fragmentos)


def valor(propiedad: Optional[dict[str, Any]]) -> Any:
    """El valor Python de una propiedad, venga de la API o de lo que se va a
    escribir. None si la propiedad no existe o está vacía."""
    if not propiedad:
        return None
    if "title" in propiedad:
        return _texto_plano(propiedad["title"]) or None
    if "rich_text" in propiedad:
        return _texto_plano(propiedad["rich_text"]) or None
    if "number" in propiedad:
        return propiedad["number"]
    if "select" in propiedad:
        return (propiedad["select"] or {}).get("name")
    if "multi_select" in propiedad:
        return [o["name"] for o in propiedad["multi_select"]]
    if "date" in propiedad:
        inicio = (propiedad["date"] or {}).get("start")
        return date.fromisoformat(inicio[:10]) if inicio else None
    if "checkbox" in propiedad:
        return bool(propiedad["checkbox"])
    if "relation" in propiedad:
        return [r["id"].replace("-", "") for r in propiedad["relation"]]
    return None


def leer(pagina: dict[str, Any], nombre: str) -> Any:
    return valor(pagina.get("properties", {}).get(nombre))


def cambios(pagina: Optional[dict[str, Any]], deseadas: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Las propiedades de `deseadas` cuyo valor difiere del de la página."""
    if pagina is None:
        return dict(deseadas)
    return {n: p for n, p in deseadas.items() if leer(pagina, n) != valor(p)}
