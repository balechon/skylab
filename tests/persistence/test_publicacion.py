# Publicar la semana: Garmin falso que registra las llamadas → Postgres real.

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from persistence import repository as repo
from sync.garmin import ErrorGarmin
from sync.publicacion import NadaQuePublicar, publicar_semana
from tests.agent.planes import HOY, plan_valido


class GarminFalso:
    def __init__(self):
        self.llamadas = []
        self.siguiente_id = 1000
        self.calendario = {}  # workout_id -> (scheduled_id, fecha)
        self.borrado_a_mano = set()

    async def subir_entrenamiento(self, entrenamiento):
        self.siguiente_id += 1
        self.llamadas.append(("subir", entrenamiento["workoutName"]))
        return self.siguiente_id

    async def programar(self, workout_id, fecha):
        self.llamadas.append(("programar", workout_id, fecha))
        self.calendario[workout_id] = (workout_id + 50000, fecha)

    async def programados_entre(self, desde, hasta):
        return [
            {"workout_id": w, "scheduled_workout_id": s, "date": f.isoformat()}
            for w, (s, f) in self.calendario.items()
            if desde <= f <= hasta
        ]

    async def desprogramar(self, scheduled_workout_id):
        self.llamadas.append(("desprogramar", scheduled_workout_id))
        self.calendario = {w: v for w, v in self.calendario.items() if v[0] != scheduled_workout_id}

    async def borrar_entrenamiento(self, workout_id):
        if workout_id in self.borrado_a_mano:
            raise ErrorGarmin(f"delete_workout falló: workout {workout_id} not found")
        self.llamadas.append(("borrar", workout_id))


@pytest.fixture
def sesiones_db(engine):
    fabrica = sessionmaker(bind=engine, expire_on_commit=False)
    yield fabrica
    with engine.begin() as conexion:
        conexion.execute(text("TRUNCATE publicacion_garmin, ejecucion_agente, plan_version, plan RESTART IDENTITY CASCADE"))


def _crear_plan(sesiones_db, plan):
    with sesiones_db.begin() as db:
        return repo.crear_plan(db, plan, perfil="ejemplo_didactico")


def test_sin_plan_activo_no_hay_nada_que_publicar(sesiones_db):
    with pytest.raises(NadaQuePublicar):
        asyncio.run(publicar_semana(sesiones_db, GarminFalso(), hoy=HOY))


def test_primera_publicacion_sube_y_programa_las_sesiones_con_carga(sesiones_db):
    plan_id = _crear_plan(sesiones_db, plan_valido())
    garmin = GarminFalso()

    r = asyncio.run(publicar_semana(sesiones_db, garmin, hoy=HOY))

    # La semana detallada tiene 5 sesiones: 2 descansos (no se publican) y 3 con carga.
    assert [p.nombre for p in r.publicados] == ["PB 13/10 Series", "PB 14/10 Recuperación", "PB 15/10 Base"]
    assert [ll[0] for ll in garmin.llamadas] == ["subir", "programar"] * 3
    with sesiones_db() as db:
        guardadas = repo.publicaciones_activas(db, HOY, HOY.replace(day=31))
    assert [(p.plan_id, p.version) for p in guardadas] == [(plan_id, 1)] * 3


def test_publicar_otra_vez_la_misma_version_no_hace_nada(sesiones_db):
    _crear_plan(sesiones_db, plan_valido())
    asyncio.run(publicar_semana(sesiones_db, GarminFalso(), hoy=HOY))

    garmin = GarminFalso()
    r = asyncio.run(publicar_semana(sesiones_db, garmin, hoy=HOY))
    assert r.sin_cambios and garmin.llamadas == []


def test_una_version_nueva_retira_lo_anterior_y_publica_lo_nuevo(sesiones_db):
    plan_id = _crear_plan(sesiones_db, plan_valido())
    garmin = GarminFalso()
    primera = asyncio.run(publicar_semana(sesiones_db, garmin, hoy=HOY))
    with sesiones_db.begin() as db:
        repo.guardar_version(db, plan_id, plan_valido(version=2), motivo="ajuste")

    garmin.llamadas.clear()
    r = asyncio.run(publicar_semana(sesiones_db, garmin, hoy=HOY))

    assert r.retirados == 3
    borrados = [ll[1] for ll in garmin.llamadas if ll[0] == "borrar"]
    assert borrados == [p.garmin_workout_id for p in primera.publicados]
    assert sum(1 for ll in garmin.llamadas if ll[0] == "desprogramar") == 3
    with sesiones_db() as db:
        activas = repo.publicaciones_activas(db, HOY, HOY.replace(day=31))
    assert {p.version for p in activas} == {2} and len(activas) == 3


def test_lo_borrado_a_mano_en_garmin_no_bloquea_la_publicacion(sesiones_db):
    plan_id = _crear_plan(sesiones_db, plan_valido())
    garmin = GarminFalso()
    primera = asyncio.run(publicar_semana(sesiones_db, garmin, hoy=HOY))
    garmin.borrado_a_mano.add(primera.publicados[0].garmin_workout_id)
    with sesiones_db.begin() as db:
        repo.guardar_version(db, plan_id, plan_valido(version=2), motivo="ajuste")

    r = asyncio.run(publicar_semana(sesiones_db, garmin, hoy=HOY))
    assert r.retirados == 3 and len(r.publicados) == 3
    assert len(r.avisos) == 1 and "not found" in r.avisos[0]
