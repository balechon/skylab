import pytest
from fastapi.testclient import TestClient

from pb_coach.api.app import app, obtener_cliente_llm, obtener_sesiones_db

TOKEN = "token-de-prueba"
CABECERA = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("PB_COACH_API_TOKEN", TOKEN)
    app.dependency_overrides[obtener_sesiones_db] = lambda: None
    app.dependency_overrides[obtener_cliente_llm] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_no_necesita_token():
    respuesta = TestClient(app).get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}


def test_sin_token_configurado_la_api_no_opera(cliente, monkeypatch):
    monkeypatch.delenv("PB_COACH_API_TOKEN")
    assert cliente.post("/semana/ajustar", headers=CABECERA).status_code == 503


def test_token_incorrecto_o_ausente(cliente):
    assert cliente.post("/semana/ajustar").status_code == 401
    assert cliente.post("/semana/ajustar", headers={"Authorization": "Bearer otro"}).status_code == 401


def test_la_api_ya_no_expone_sync(cliente):
    assert cliente.post("/sync", headers=CABECERA).status_code == 404


def test_plan_con_perfil_inexistente(cliente):
    solicitud = {"modo": "Construcción", "perfil": "no_existe", "fecha_objetivo": "2026-12-31"}
    respuesta = cliente.post("/plan", headers=CABECERA, json=solicitud)
    assert respuesta.status_code == 404


def test_plan_con_solicitud_invalida(cliente):
    respuesta = cliente.post("/plan", headers=CABECERA, json={"modo": "Inventado", "perfil": "x", "fecha_objetivo": "2026-12-31"})
    assert respuesta.status_code == 422
