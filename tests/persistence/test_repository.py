# Tests contra un Postgres real. Necesitan TEST_DATABASE_URL (la define el
# servicio `test` del compose); sin ella se saltan.
#
#   docker compose run --rm --build test
#
# Los fixtures `engine` (esquema temporal con las migraciones aplicadas) y
# `db` (transacción que se deshace al final) están en conftest.py.

from datetime import date, timedelta

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pydantic import ValidationError

from core.training import (
    ClaseSesion,
    Mesociclo,
    Microciclo,
    ModoPlan,
    ObjetivoMesociclo,
    ObjetivosMicrociclo,
    Plan,
    SesionRealizada,
    Terreno,
    TipoMicrociclo,
    TipoSesion,
    ZonasFC,
)
from persistence import repository as repo
from persistence.models import Base, PlanVersionFila

def _sesion(dia: int, garmin_id=None, **campos) -> SesionRealizada:
    return SesionRealizada(
        fecha=date(2026, 10, 12) + timedelta(days=dia),
        duracion=timedelta(minutes=campos.pop("minutos", 60)),
        distancia_km=campos.pop("km", 10.0),
        garmin_activity_id=garmin_id,
        **campos,
    )


def _plan(version: int = 1, km: float = 40) -> Plan:
    micro = Microciclo(
        fecha_inicio=date(2026, 10, 12),
        fecha_fin=date(2026, 10, 18),
        tipo_microciclo=TipoMicrociclo.CARGA,
        objetivos=ObjetivosMicrociclo(volumen_km=km, duracion=timedelta(hours=5), sesiones_por_clase={ClaseSesion.FONDO: 3}),
    )
    meso = Mesociclo(
        objetivo=ObjetivoMesociclo.BASE_AEROBICA,
        fecha_inicio=date(2026, 10, 12),
        fecha_fin=date(2026, 11, 8),
        microciclos=[micro],
    )
    return Plan(
        modo=ModoPlan.CONSTRUCCION,
        fecha_inicio=date(2026, 10, 12),
        fecha_objetivo=date(2026, 12, 31),
        version=version,
        mesociclos=[meso],
    )


# ---------- esquema ----------

def test_la_migracion_coincide_con_los_modelos(engine):
    with engine.connect() as conexion:
        diferencias = compare_metadata(MigrationContext.configure(conexion), Base.metadata)
    assert diferencias == []


# ---------- sesiones realizadas ----------

def test_sesion_ida_y_vuelta_conserva_todos_los_campos(db):
    original = _sesion(
        1,
        garmin_id=9_876_543_210,
        terreno=Terreno.SENDERO_TECNICO,
        clase_sesion=ClaseSesion.ESPECIFICO,
        tipo_sesion=TipoSesion.SERIES,
        desnivel_positivo_m=420,
        fc_media=161,
        segundos_por_zona={ZonasFC.Z2: 1200.5, ZonasFC.Z4: 2994.4},
        rpe=8,
        sensaciones="Piernas pesadas en la subida",
        carga_epoc=145.5,
    )
    repo.guardar_sesiones(db, [original])
    assert repo.sesiones_entre(db, original.fecha, original.fecha) == [original]


def test_el_sync_no_duplica_por_garmin_activity_id(db):
    assert repo.guardar_sesiones(db, [_sesion(0, garmin_id=1), _sesion(1, garmin_id=2)]) == 2
    assert repo.guardar_sesiones(db, [_sesion(1, garmin_id=2), _sesion(2, garmin_id=3)]) == 1
    assert len(repo.sesiones_entre(db, date(2026, 10, 1), date(2026, 10, 31))) == 3


def test_sesiones_entre_filtra_y_ordena(db):
    repo.guardar_sesiones(db, [_sesion(5, garmin_id=5), _sesion(1, garmin_id=1), _sesion(20, garmin_id=20)])
    fechas = [s.fecha for s in repo.sesiones_entre(db, date(2026, 10, 12), date(2026, 10, 18))]
    assert fechas == [date(2026, 10, 13), date(2026, 10, 17)]


def test_ultima_fecha_sincronizada(db):
    assert repo.ultima_fecha_sincronizada(db) is None
    repo.guardar_sesiones(db, [_sesion(3, garmin_id=3), _sesion(1, garmin_id=1)])
    assert repo.ultima_fecha_sincronizada(db) == date(2026, 10, 15)


# ---------- planes y versiones ----------

def test_crear_plan_y_leer_el_vigente(db):
    plan = _plan()
    plan_id = repo.crear_plan(db, plan, perfil="ejemplo_didactico")
    assert repo.plan_vigente(db) == (plan_id, plan)


def test_crear_plan_exige_version_1(db):
    with pytest.raises(ValueError, match="versión 1"):
        repo.crear_plan(db, _plan(version=2), perfil="x")


def test_nueva_version_pasa_a_ser_la_vigente_y_queda_el_historial(db):
    plan_id = repo.crear_plan(db, _plan(), perfil="x")
    repo.guardar_version(db, plan_id, _plan(version=2, km=36), motivo="EJEMPLO-AJUSTE-001: repetir_microciclo")

    _, vigente = repo.plan_vigente(db)
    assert (vigente.version, vigente.mesociclos[0].microciclos[0].objetivos.volumen_km) == (2, 36)
    historial = repo.historial_versiones(db, plan_id)
    assert [(v, m) for v, m, _ in historial] == [(1, "crear_ciclo"), (2, "EJEMPLO-AJUSTE-001: repetir_microciclo")]


def test_guardar_version_no_salta_ni_sobrescribe_versiones(db):
    plan_id = repo.crear_plan(db, _plan(), perfil="x")
    with pytest.raises(ValueError, match="Se esperaba la versión 2"):
        repo.guardar_version(db, plan_id, _plan(version=3), motivo="salto")
    with pytest.raises(ValueError, match="Se esperaba la versión 2"):
        repo.guardar_version(db, plan_id, _plan(version=1), motivo="sobrescritura")


def test_crear_un_ciclo_nuevo_desactiva_el_anterior(db):
    repo.crear_plan(db, _plan(), perfil="uphill_athlete")
    nuevo_id = repo.crear_plan(db, _plan(km=50), perfil="nacho_martinez")
    plan_id, vigente = repo.plan_vigente(db)
    assert plan_id == nuevo_id
    assert vigente.mesociclos[0].microciclos[0].objetivos.volumen_km == 50


def test_un_plan_corrupto_en_la_base_no_entra_al_motor(db):
    plan_id = repo.crear_plan(db, _plan(), perfil="x")
    corrupto = _plan(version=2).model_dump(mode="json")
    corrupto["fecha_objetivo"] = "2026-01-01"  # antes de fecha_inicio
    db.add(PlanVersionFila(plan_id=plan_id, version=2, motivo="manual", contenido=corrupto))
    db.flush()
    with pytest.raises(ValidationError):
        repo.plan_vigente(db)


# ---------- ejecuciones ----------

def test_registrar_ejecucion(db):
    plan_id = repo.crear_plan(db, _plan(), perfil="x")
    version_id = repo.guardar_version(db, plan_id, _plan(version=2), motivo="ajuste")
    ejecucion_id = repo.registrar_ejecucion(
        db,
        operacion="ajuste_semanal",
        estado="plan_valido",
        resultado={"accion": "progresar"},
        plan_version_id=version_id,
        modelo="claude-opus-5-5",
        tokens_entrada=12_000,
        tokens_salida=1_800,
    )
    assert ejecucion_id > 0


# ---------- ficha del atleta ----------

def test_la_ficha_vigente_es_la_ultima_guardada(db):
    from core.athlete import FichaAtleta, Umbrales

    assert repo.ficha_vigente(db) is None
    repo.guardar_ficha(db, FichaAtleta(edad=31, umbrales=Umbrales(fc_aerobico=149)))
    repo.guardar_ficha(db, FichaAtleta(edad=31, umbrales=Umbrales(fc_aerobico=149, fc_lactato=170)))
    assert repo.ficha_vigente(db).umbrales.fc_lactato == 170
