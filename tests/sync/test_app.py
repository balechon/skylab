# HTTP del servicio de sync, con un sincronizador falso (sin Garmin ni BD).

import asyncio
from datetime import date

import pytest
from starlette.testclient import TestClient

from sync.app import crear_app
from sync.sincronizacion import ResultadoSync

TOKEN = "token-de-prueba"
CABECERA = {"Authorization": f"Bearer {TOKEN}"}


async def _sincroniza_bien(_db):
    return ResultadoSync(desde=date(2026, 10, 1), hasta=date(2026, 10, 6), traidas=3, nuevas=1)


async def _garmin_caido(_db):
    raise ConnectionError("garmin-mcp no responde")


def _cliente(sincronizar=_sincroniza_bien):
    return TestClient(crear_app(sincronizar=sincronizar, fabrica_sesiones=lambda: None))


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("PB_COACH_API_TOKEN", TOKEN)


def test_health_no_necesita_token():
    assert _cliente().get("/health").json() == {"status": "ok"}


def test_sync_exige_token(monkeypatch):
    assert _cliente().post("/sync").status_code == 401
    monkeypatch.delenv("PB_COACH_API_TOKEN")
    assert _cliente().post("/sync", headers=CABECERA).status_code == 503


def test_sync_correcto():
    respuesta = _cliente().post("/sync", headers=CABECERA)
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "ok": True,
        "resultado": {"desde": "2026-10-01", "hasta": "2026-10-06", "traidas": 3, "nuevas": 1},
    }


def test_garmin_caido_devuelve_502_con_el_error():
    respuesta = _cliente(_garmin_caido).post("/sync", headers=CABECERA)
    assert respuesta.status_code == 502
    assert respuesta.json() == {"ok": False, "error": "ConnectionError: garmin-mcp no responde"}


async def _garmin_caido_como_mcp(_db):
    # Así llega un fallo de conexión desde el SDK de MCP: un grupo que mezcla
    # el error real con cancelaciones internas.
    raise BaseExceptionGroup(
        "unhandled errors in a TaskGroup",
        [asyncio.CancelledError(), ConnectionError("Temporary failure in name resolution")],
    )


def test_el_grupo_de_excepciones_de_mcp_devuelve_502_con_la_causa_real():
    respuesta = _cliente(_garmin_caido_como_mcp).post("/sync", headers=CABECERA)
    assert respuesta.status_code == 502
    assert respuesta.json()["error"] == "ConnectionError: Temporary failure in name resolution"
