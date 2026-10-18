import asyncio
from datetime import date, timedelta

from notion import propiedades as p
from notion.clientes import RespuestaSkylab
from notion.servicio import ServicioNotion
from tests.agent.planes import HOY, plan_valido
from tests.notion.falsos import NotionFalso, SkylabFalso
from tests.notion.test_traduccion import FILA_ATLETA

ATLETA, SEMANAS, ENTRENAMIENTOS = "ds-atleta", "ds-semanas", "ds-entrenamientos"
MARTES = HOY + timedelta(days=1)


def _plan_api(plan=None, version=1):
    plan = plan or plan_valido()
    return {"plan_id": 4, "version": version, "perfil": "uphill_athlete", "plan": plan.model_dump(mode="json")}


def _servicio(notion, skylab, hoy=HOY):
    return ServicioNotion(notion, skylab, ATLETA, SEMANAS, ENTRENAMIENTOS, hoy=lambda: hoy)


def _ciclo(servicio):
    return asyncio.run(servicio.ciclo())


# ---------- volcado del plan ----------

def test_vuelca_semanas_y_sesiones_y_un_segundo_ciclo_no_escribe_nada():
    notion, skylab = NotionFalso(), SkylabFalso(plan=_plan_api())
    servicio = _servicio(notion, skylab)

    resumen = _ciclo(servicio)
    assert len(notion.filas(SEMANAS)) == 4  # las 4 semanas del bloque de base
    claves = sorted(p.leer(f, "Clave") for f in notion.filas(ENTRENAMIENTOS))
    assert claves == [f"{HOY + timedelta(days=d)}#1" for d in (1, 2, 3)]
    sesion = notion.fila(ENTRENAMIENTOS, f"{MARTES}#1")
    semana = notion.fila(SEMANAS, HOY.isoformat())
    assert p.leer(sesion, "Semana") == [semana["id"]]
    assert p.leer(semana, "Estado") == "Planificada"
    assert resumen.filas_creadas == 7

    notion.creadas.clear(), notion.actualizadas.clear()
    _ciclo(servicio)
    assert notion.creadas == [] and notion.actualizadas == []


def test_adopta_las_filas_creadas_a_mano():
    notion = NotionFalso()
    a_mano = notion.anadir(SEMANAS, {"Semana": p.titulo("S1 · a mano"), "Inicio": p.fecha(HOY), "Observaciones": p.texto("Ojo")})
    sesion = notion.anadir(ENTRENAMIENTOS, {"Sesión": p.titulo("Mar"), "Fecha": p.fecha(MARTES), "Comentario": p.texto("Bien")})
    _ciclo(_servicio(notion, SkylabFalso(plan=_plan_api())))

    assert len(notion.filas(SEMANAS)) == 4 and len(notion.filas(ENTRENAMIENTOS)) == 3
    assert p.leer(notion.bases[SEMANAS][a_mano], "Clave") == HOY.isoformat()
    assert p.leer(notion.bases[SEMANAS][a_mano], "Observaciones") == "Ojo"  # lo del atleta no se toca
    assert p.leer(notion.bases[ENTRENAMIENTOS][sesion], "Clave") == f"{MARTES}#1"
    assert p.leer(notion.bases[ENTRENAMIENTOS][sesion], "Comentario") == "Bien"


def test_una_sesion_que_sale_del_plan_se_conserva_desmarcada():
    notion, skylab = NotionFalso(), SkylabFalso(plan=_plan_api())
    servicio = _servicio(notion, skylab)
    _ciclo(servicio)

    nuevo = plan_valido(version=2)
    nuevo.mesociclos[0].microciclos[0].sesiones = [s for s in nuevo.mesociclos[0].microciclos[0].sesiones if s.fecha != MARTES]
    skylab.plan_actual = _plan_api(nuevo, version=2)
    _ciclo(servicio)

    retirada = notion.fila(ENTRENAMIENTOS, f"{MARTES}#1")
    assert retirada is not None and p.leer(retirada, "Vigente") is False
    assert p.leer(notion.fila(SEMANAS, HOY.isoformat()), "Versión del plan") == 2


def test_lo_realizado_va_a_su_sesion_y_lo_no_planificado_a_una_fila_propia():
    actividades = [
        {"garmin_activity_id": 11, "fecha": MARTES.isoformat(), "duracion": "PT32M", "distancia_km": 6.1, "fc_media": 142},
        {"garmin_activity_id": 12, "fecha": (HOY + timedelta(days=5)).isoformat(), "duracion": "PT20M", "distancia_km": 3.0},
    ]
    notion, skylab = NotionFalso(), SkylabFalso(plan=_plan_api(), sesiones=actividades)
    servicio = _servicio(notion, skylab, hoy=HOY + timedelta(days=6))
    _ciclo(servicio)

    martes = notion.fila(ENTRENAMIENTOS, f"{MARTES}#1")
    assert (p.leer(martes, "Hecho: duración (min)"), p.leer(martes, "Hecho: FC media")) == (32, 142)
    extra = notion.fila(ENTRENAMIENTOS, "garmin:12")
    assert extra is not None and p.leer(extra, "Sesión").endswith("Actividad extra")

    antes = len(notion.filas(ENTRENAMIENTOS))
    _ciclo(servicio)
    assert len(notion.filas(ENTRENAMIENTOS)) == antes  # sin duplicar


# ---------- ficha ----------

def test_la_ficha_se_envia_solo_si_cambia():
    notion = NotionFalso()
    fila = notion.anadir(ATLETA, FILA_ATLETA["properties"])
    skylab = SkylabFalso()
    servicio = _servicio(notion, skylab)

    _ciclo(servicio)
    assert skylab.nombres().count("guardar_atleta") == 1
    assert "Ficha enviada" in p.leer(notion.bases[ATLETA][fila], "Mensaje SKYLAB")

    _ciclo(servicio)
    assert skylab.nombres().count("guardar_atleta") == 1  # sin cambios, no se reenvía


def test_una_ficha_imposible_no_se_envia_y_se_avisa():
    notion = NotionFalso()
    fila = notion.anadir(ATLETA, dict(FILA_ATLETA["properties"], **{"AeT (ppm)": p.numero(190)}))
    skylab = SkylabFalso()
    resumen = _ciclo(_servicio(notion, skylab))
    assert "guardar_atleta" not in skylab.nombres()
    assert "no válida" in p.leer(notion.bases[ATLETA][fila], "Mensaje SKYLAB") and resumen.avisos


# ---------- Evaluar / Recalcular ----------

DOMINGO = HOY + timedelta(days=6)
LUNES_SIGUIENTE = HOY + timedelta(days=7)


def _con_peticion(campo="Evaluar", hoy=LUNES_SIGUIENTE):
    notion, skylab = NotionFalso(), SkylabFalso(plan=_plan_api())
    servicio = _servicio(notion, skylab, hoy=hoy)
    _ciclo(servicio)  # vuelca el plan
    semana = notion.fila(SEMANAS, HOY.isoformat())
    notion.bases[SEMANAS][semana["id"]]["properties"].update(
        {campo: p.casilla(True), "Observaciones": p.texto("Viajo el jueves.")}
    )
    martes = notion.fila(ENTRENAMIENTOS, f"{MARTES}#1")
    notion.bases[ENTRENAMIENTOS][martes["id"]]["properties"]["Comentario"] = p.texto("Me costaron las series.")
    skylab.llamadas.clear()
    return notion, skylab, servicio, semana["id"]


def test_evaluar_lanza_el_ajuste_con_los_comentarios_y_escribe_el_feedback():
    notion, skylab, servicio, semana = _con_peticion()
    skylab.respuesta_ajuste = RespuestaSkylab(200, {
        "estado": "plan_valido", "version": 2,
        "feedback": {"lo_que_paso": "Semana completa.", "por_que_cambia": "Se sigue el plan.",
                     "consejos": [{"texto": "Camina las rampas.", "regla_id": None}]},
    })
    resumen = _ciclo(servicio)

    ajuste = next(a for n, a in skylab.llamadas if n == "ajustar")
    assert ajuste == {"forzar": False, "comentarios": {
        "general": "Viajo el jueves.", "por_sesion": [{"fecha": MARTES.isoformat(), "texto": "Me costaron las series."}]}}
    assert skylab.nombres().index("sincronizar") < skylab.nombres().index("ajustar") < skylab.nombres().index("publicar")
    fila = notion.bases[SEMANAS][semana]
    assert p.leer(fila, "Evaluar") is False and p.leer(fila, "Qué pasó") == "Semana completa."
    assert p.leer(fila, "Consejos") == "• Camina las rampas." and p.leer(fila, "Estado") == "Evaluada"
    assert "plan v2" in p.leer(fila, "Mensaje SKYLAB") and resumen.peticiones


def test_evaluar_una_semana_que_no_ha_terminado_no_llama_al_modelo():
    notion, skylab, servicio, semana = _con_peticion(hoy=DOMINGO)
    _ciclo(servicio)
    assert "ajustar" not in skylab.nombres()
    fila = notion.bases[SEMANAS][semana]
    assert p.leer(fila, "Evaluar") is False and "aún no ha terminado" in p.leer(fila, "Mensaje SKYLAB")


def test_recalcular_fuerza_el_ajuste():
    notion, skylab, servicio, semana = _con_peticion(campo="Recalcular")
    _ciclo(servicio)
    assert next(a for n, a in skylab.llamadas if n == "ajustar")["forzar"] is True
    assert p.leer(notion.bases[SEMANAS][semana], "Recalcular") is False


def test_si_la_api_rechaza_el_ajuste_se_avisa_y_se_desmarca():
    notion, skylab, servicio, semana = _con_peticion(campo="Recalcular")
    skylab.respuesta_ajuste = RespuestaSkylab(409, {"detail": "La semana ya se recalculó 2 veces (máximo 2)."})
    _ciclo(servicio)
    fila = notion.bases[SEMANAS][semana]
    assert p.leer(fila, "Recalcular") is False and "2 veces" in p.leer(fila, "Mensaje SKYLAB")
    assert "publicar" not in skylab.nombres()


def test_solo_una_peticion_por_ciclo():
    notion, skylab, servicio, _ = _con_peticion()
    otra = notion.fila(SEMANAS, (HOY + timedelta(weeks=1)).isoformat())
    notion.bases[SEMANAS][otra["id"]]["properties"]["Recalcular"] = p.casilla(True)
    _ciclo(servicio)
    assert skylab.nombres().count("ajustar") == 1


def test_garmin_se_sincroniza_cada_diez_ciclos():
    skylab = SkylabFalso()
    servicio = _servicio(NotionFalso(), skylab)
    for _ in range(11):
        _ciclo(servicio)
    assert skylab.nombres().count("sincronizar") == 2



# ---------- monitor ----------

def test_vuelca_el_monitor_sin_duplicar():
    from datetime import datetime, timezone

    notion, skylab = NotionFalso(), SkylabFalso()
    skylab.gold = {
        "resumen": {"ejecuciones": 1, "aceptadas": 1, "coste_total_usd": 0.6566, "tokens_entrada": 78959,
                    "ultima_ejecucion": "2026-10-18T13:45:36.850601-05:00"},
        "ejecuciones": [{"id": 4, "operacion": "crear_ciclo", "estado": "plan_valido", "aceptada": True,
                         "creado_en": "2026-10-18T13:45:36.850601-05:00", "coste_usd": 0.6566}],
        "semanas": [{"semana": "2026-10-19", "tipo": "Base", "horas_objetivo": 3.58, "horas_hechas": 0}],
        "por_mes": [],
    }
    instante = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)
    servicio = ServicioNotion(notion, skylab, ATLETA, SEMANAS, ENTRENAMIENTOS, hoy=lambda: HOY,
                              ds_resumen="r", ds_ejecuciones="e", ds_carga="c", ahora=lambda: instante)
    _ciclo(servicio)
    assert p.leer(notion.fila("e", "4"), "Coste (USD)") == 0.6566
    assert p.leer(notion.fila("c", "2026-10-19"), "Semana") == "19–25 oct"
    total = notion.fila("r", "total")
    assert p.leer(total, "Ejecuciones") == 1 and p.leer(total, "Último ciclo del servicio") == instante

    notion.creadas.clear()
    _ciclo(servicio)
    assert notion.creadas == []  # todo se actualiza en su fila
