# Traducción Garmin → SesionRealizada, sin red. Los diccionarios tienen la
# misma forma que devuelve garmin-mcp; los valores son sintéticos.

import asyncio

import pytest
from datetime import date, timedelta

from core.training import Terreno, ZonasFC
from sync.garmin import ClienteGarmin, actividad_a_sesion, traer_sesiones


def resumen_garmin(id_=1, tipo="trail_running", inicio="2026-10-10 07:00:00", **campos):
    base = {
        "id": id_,
        "type": tipo,
        "start_time": inicio,
        "duration_seconds": 4800.4,
        "distance_meters": 9000.0,
        "elevation_gain_meters": 400.0,
        "elevation_loss_meters": 410.0,
        "avg_hr_bpm": 158.6,
    }
    base.update(campos)
    return base


DETALLE = {"training_load": 201.83, "workout_rpe": 60, "workout_feel": 75}
ZONAS = [
    {"zoneNumber": 1, "secsInZone": 60.2},
    {"zoneNumber": 2, "secsInZone": 1500.0},
    {"zoneNumber": 3, "secsInZone": 0},
    {"zoneNumber": 4, "secsInZone": 3000.55},
]


class ClienteGarminFalso:
    """Mismo contrato que ClienteGarmin, con datos en memoria."""

    def __init__(self, actividades):
        self.actividades = actividades
        self.detalles_pedidos = []

    async def actividades_entre(self, desde, hasta):
        return [a for a in self.actividades if desde <= date.fromisoformat(a["start_time"][:10]) <= hasta]

    async def detalle(self, activity_id):
        self.detalles_pedidos.append(activity_id)
        return DETALLE

    async def zonas_fc(self, activity_id):
        return ZONAS


def test_traduce_una_actividad_de_trail():
    s = actividad_a_sesion(resumen_garmin(), DETALLE, ZONAS)
    assert s.garmin_activity_id == 1
    assert s.fecha == date(2026, 10, 10)
    assert s.duracion == timedelta(seconds=4800)
    assert s.distancia_km == 9.0
    assert (s.desnivel_positivo_m, s.desnivel_negativo_m) == (400.0, 410.0)
    assert s.fc_media == 159
    assert s.carga_epoc == 201.8
    assert s.rpe == 6  # Garmin lo guarda x10
    assert s.sensaciones == "Fuerte"
    assert s.ritmo_medio_min_km == 8.89
    assert s.clase_sesion is None  # la clasificación es de engine/


def test_en_trail_no_se_inventa_el_terreno():
    assert actividad_a_sesion(resumen_garmin(), DETALLE, ZONAS).terreno is None


def test_running_es_asfalto_y_track_es_pista():
    assert actividad_a_sesion(resumen_garmin(tipo="running"), DETALLE, ZONAS).terreno == Terreno.ASFALTO
    assert actividad_a_sesion(resumen_garmin(tipo="track_running"), DETALLE, ZONAS).terreno == Terreno.PISTA


def test_guarda_el_tiempo_real_por_zona_sin_zonas_vacias():
    s = actividad_a_sesion(resumen_garmin(), DETALLE, ZONAS)
    assert s.segundos_por_zona == {ZonasFC.Z1: 60.2, ZonasFC.Z2: 1500.0, ZonasFC.Z4: 3000.6}


def test_ignora_lo_que_no_es_running():
    assert actividad_a_sesion(resumen_garmin(tipo="cycling"), DETALLE, ZONAS) is None
    assert actividad_a_sesion(resumen_garmin(tipo="strength_training"), DETALLE, ZONAS) is None


def test_ignora_rpe_y_sensaciones_anteriores_a_la_fecha_de_corte():
    corte = date(2026, 10, 7)
    antes = actividad_a_sesion(resumen_garmin(inicio="2026-10-02 07:00:00"), DETALLE, ZONAS, rpe_desde=corte)
    despues = actividad_a_sesion(resumen_garmin(inicio="2026-10-07 07:00:00"), DETALLE, ZONAS, rpe_desde=corte)
    assert (antes.rpe, antes.sensaciones) == (None, None)
    assert (despues.rpe, despues.sensaciones) == (6, "Fuerte")
    assert antes.carga_epoc == 201.8  # la carga EPOC no depende de la fecha de corte


def test_campos_ausentes_quedan_vacios():
    detalle_vacio = {"training_load": None, "workout_rpe": None, "workout_feel": None}
    s = actividad_a_sesion(resumen_garmin(avg_hr_bpm=None, distance_meters=0), detalle_vacio, [])
    assert (s.fc_media, s.carga_epoc, s.rpe, s.sensaciones, s.ritmo_medio_min_km) == (None, None, None, None, None)
    assert s.segundos_por_zona == {}


def test_traer_sesiones_solo_pide_detalle_de_running():
    cliente = ClienteGarminFalso(
        [resumen_garmin(1), resumen_garmin(2, tipo="cycling"), resumen_garmin(3, tipo="running")]
    )
    sesiones = asyncio.run(traer_sesiones(cliente, date(2026, 10, 1), date(2026, 10, 31)))
    assert [s.garmin_activity_id for s in sesiones] == [1, 3]
    assert cliente.detalles_pedidos == [1, 3]


class ClientePaginado(ClienteGarmin):
    """Simula la paginación real de garmin-mcp: páginas desde 0, 2 por página."""

    def __init__(self, total):
        super().__init__(url="http://no-se-usa")
        self.total = total
        self.paginas_pedidas = []

    async def _llamar(self, tool, argumentos):
        pagina = argumentos["page"]
        self.paginas_pedidas.append(pagina)
        ids = list(range(self.total))[pagina * 2 : pagina * 2 + 2]
        return {"activities": [{"id": i} for i in ids], "has_more": (pagina + 1) * 2 < self.total}


def test_paginacion_empieza_en_cero_y_recorre_todas():
    cliente = ClientePaginado(total=5)
    actividades = asyncio.run(cliente.actividades_entre(date(2026, 10, 1), date(2026, 10, 31)))
    assert [a["id"] for a in actividades] == [0, 1, 2, 3, 4]
    assert cliente.paginas_pedidas == [0, 1, 2]


# ---------- errores que garmin-mcp devuelve como texto ----------

from sync.garmin import ErrorGarmin, _interpretar  # noqa: E402


def test_un_error_en_texto_plano_se_convierte_en_error():
    with pytest.raises(ErrorGarmin, match="Error uploading workout"):
        _interpretar("upload_workout", "Error uploading workout: 400 Bad Request")


def test_un_status_failed_se_convierte_en_error():
    with pytest.raises(ErrorGarmin, match="HTTP 500"):
        _interpretar("schedule_workout", '{"status": "failed", "message": "Failed to schedule workout: HTTP 500"}')


def test_sin_entrenamientos_programados_es_una_lista_vacia():
    assert _interpretar("get_scheduled_workouts", "No workouts scheduled between 2026-10-19 and 2026-10-25.") == {
        "scheduled_workouts": []
    }



# ---------- límites de zona ----------

ZONAS_CON_LIMITES = [
    {"zoneNumber": n, "secsInZone": s, "zoneLowBoundary": b}
    for n, s, b in [(1, 600.0, 131), (2, 1200.0, 148), (3, 300.0, 164), (4, 0, 179), (5, 0, 190)]
]


def test_guarda_los_limites_de_zona_con_los_que_se_registro():
    s = actividad_a_sesion(resumen_garmin(), DETALLE, ZONAS_CON_LIMITES)
    assert s.limites_zonas == [131, 148, 164, 179, 190]


def test_sin_limites_completos_no_se_inventan():
    assert actividad_a_sesion(resumen_garmin(), DETALLE, ZONAS).limites_zonas == []
