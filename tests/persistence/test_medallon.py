# Pipeline medallón contra Postgres real: bronze (crudo), silver y gold (vistas).

from datetime import date, timedelta

from core.training import SesionRealizada, ZonasFC
from persistence import repository as repo
from tests.agent.planes import HOY, plan_valido


def test_bronze_guarda_y_reemplaza_lo_crudo_de_garmin(db):
    cruda = {"garmin_activity_id": 7, "fecha": HOY, "resumen": {"id": 7}, "detalle": {"a": 1}, "zonas": []}
    assert repo.guardar_bronze(db, [cruda]) == 1
    assert repo.guardar_bronze(db, [dict(cruda, detalle={"a": 2})]) == 1  # misma actividad: se reemplaza
    filas = repo._filas(db, "SELECT detalle FROM bronze_garmin_actividad")
    assert filas == [{"detalle": {"a": 2}}]


def test_coste_y_velocidad_de_cada_ejecucion(db):
    repo.registrar_ejecucion(
        db, operacion="ajuste_semanal", estado="plan_valido", resultado={}, modelo="anthropic:claude-opus-5-5",
        tokens_entrada=100_000, tokens_salida=10_000, tokens_cache_lectura=60_000, tokens_cache_escritura=10_000,
        duracion_segundos=200.0,
    )
    fila = repo._filas(db, "SELECT coste_usd, tokens_salida_por_segundo, aceptada FROM silver_ejecucion")[0]
    # 30k sin caché × 4 + 60k leídos × 0,20 + 10k escritos × 5 + 10k de salida × 20, por millón
    assert float(fila["coste_usd"]) == 0.382
    assert float(fila["tokens_salida_por_segundo"]) == 50.0
    assert fila["aceptada"] is False  # sin versión del plan

    resumen = repo.monitor(db)["resumen"]
    assert resumen["ejecuciones"] == 1 and float(resumen["coste_total_usd"]) == 0.382


def test_un_modelo_sin_precio_no_tiene_coste(db):
    repo.registrar_ejecucion(db, operacion="crear_ciclo", estado="x", resultado={}, modelo="otro:modelo",
                             tokens_entrada=10, tokens_salida=10)
    assert repo._filas(db, "SELECT coste_usd FROM silver_ejecucion")[0]["coste_usd"] is None


def test_carga_y_adherencia_semanal(db):
    plan = plan_valido()
    plan.mesociclos[0].microciclos[0].objetivos.duracion = timedelta(hours=2)
    repo.crear_plan(db, plan, perfil="ejemplo_didactico")
    repo.guardar_sesiones(db, [
        SesionRealizada(garmin_activity_id=1, fecha=HOY + timedelta(days=1), duracion=timedelta(minutes=45),
                        distancia_km=8, desnivel_positivo_m=120, rpe=4, carga_epoc=90,
                        segundos_por_zona={ZonasFC.Z2: 1800.0, ZonasFC.Z3: 900.0}),
        SesionRealizada(garmin_activity_id=2, fecha=HOY + timedelta(days=3), duracion=timedelta(minutes=45),
                        distancia_km=7, rpe=6, carga_epoc=110),
    ])

    sesion = repo._filas(db, "SELECT semana, min_z2, min_z3, carga_srpe FROM silver_sesion ORDER BY id")[0]
    assert sesion["semana"] == HOY and float(sesion["min_z2"]) == 30.0 and float(sesion["carga_srpe"]) == 180.0

    semanas = repo.monitor(db)["semanas"]
    assert [s["semana"] for s in semanas] == [HOY + timedelta(weeks=i) for i in range(4)]
    primera = semanas[0]
    assert float(primera["horas_objetivo"]) == 2.0 and float(primera["horas_hechas"]) == 1.5
    assert float(primera["adherencia_horas_pct"]) == 75.0 and primera["sesiones"] == 2
    assert float(primera["km_hechos"]) == 15.0 and semanas[1]["sesiones"] == 0
