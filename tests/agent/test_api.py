import pytest
from fastapi.testclient import TestClient

from agent.api import app, obtener_modelo, obtener_sesiones_db

TOKEN = "token-de-prueba"
CABECERA = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("SKYLAB_API_TOKEN", TOKEN)
    app.dependency_overrides[obtener_sesiones_db] = lambda: None
    app.dependency_overrides[obtener_modelo] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_no_necesita_token():
    respuesta = TestClient(app).get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}


def test_sin_token_configurado_la_api_no_opera(cliente, monkeypatch):
    monkeypatch.delenv("SKYLAB_API_TOKEN")
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


def test_ajustar_acepta_comentarios_del_atleta(cliente, monkeypatch):
    from agent import servicio

    recibido = {}

    def ajuste_falso(sesiones_db, modelo, forzar=False, comentarios=None):
        recibido["comentarios"] = comentarios
        raise servicio.SinPlanVigente("sin plan")

    monkeypatch.setattr(servicio, "ajuste_semanal", ajuste_falso)
    cuerpo = {"general": "Viajo el jueves.", "por_sesion": [{"fecha": "2026-10-20", "texto": "Me costó."}]}
    respuesta = cliente.post("/semana/ajustar", headers=CABECERA, json=cuerpo)
    assert respuesta.status_code == 409
    assert recibido["comentarios"].general == "Viajo el jueves."
    assert recibido["comentarios"].por_sesion[0].texto == "Me costó."


def test_atleta_valida_la_ficha(cliente):
    respuesta = cliente.put("/atleta", headers=CABECERA, json={"edad": 31, "umbrales": {"fc_aerobico": 170, "fc_lactato": 150}})
    assert respuesta.status_code == 422
    assert cliente.put("/atleta", json={"edad": 31}).status_code == 401



def test_plan_y_sesiones_exigen_token(cliente):
    assert cliente.get("/plan").status_code == 401
    assert cliente.get("/sesiones?desde=2026-10-01&hasta=2026-10-07").status_code == 401


def test_sesiones_valida_el_rango(cliente):
    respuesta = cliente.get("/sesiones?desde=2026-10-07&hasta=2026-10-01", headers=CABECERA)
    assert respuesta.status_code == 422


def test_recalculos_agotados_devuelve_409(cliente, monkeypatch):
    from agent import servicio

    def agotado(sesiones_db, modelo, forzar=False, comentarios=None):
        raise servicio.RecalculosAgotados("ya se recalculó 2 veces")

    monkeypatch.setattr(servicio, "ajuste_semanal", agotado)
    respuesta = cliente.post("/semana/ajustar?forzar=true", headers=CABECERA)
    assert respuesta.status_code == 409 and "2 veces" in respuesta.json()["detail"]
