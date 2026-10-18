from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from core.training import (
    ClaseSesion,
    Intervalos,
    Microciclo,
    ObjetivosMicrociclo,
    RangoFC,
    SesionPlanificada,
    SesionRealizada,
    TipoMicrociclo,
    TipoSesion,
    ZonasFC,
)
from notion import propiedades as p
from notion import traduccion as t

RANGOS = {ZonasFC.REC: RangoFC(maximo=131), ZonasFC.Z1: RangoFC(minimo=131, maximo=148)}

SPRINTS = SesionPlanificada(
    fecha=date(2026, 10, 20), clase_sesion=ClaseSesion.FONDO, tipo_sesion=TipoSesion.SPRINTS_CUESTA,
    zona_fc_objetivo=ZonasFC.Z1, duracion_objetivo=timedelta(minutes=55),
    calentamiento=timedelta(minutes=20), vuelta_calma=timedelta(minutes=20),
    intervalos=Intervalos(repeticiones=6, trabajo=timedelta(seconds=10), recuperacion=timedelta(seconds=140)),
)


def _micro(inicio: date) -> Microciclo:
    return Microciclo(
        fecha_inicio=inicio, fecha_fin=inicio + timedelta(days=6), tipo_microciclo=TipoMicrociclo.BASE,
        objetivos=ObjetivosMicrociclo(duracion=timedelta(minutes=215), volumen_km=30),
    )


def test_propiedades_se_leen_igual_escritas_que_devueltas_por_la_api():
    escrita = p.texto("Hola")
    de_la_api = {"type": "rich_text", "rich_text": [{"plain_text": "Hola", "text": {"content": "Hola"}}]}
    assert p.valor(escrita) == p.valor(de_la_api) == "Hola"
    assert p.valor(p.fecha(date(2026, 10, 19))) == date(2026, 10, 19)
    assert p.valor({"type": "date", "date": {"start": "2026-10-19"}}) == date(2026, 10, 19)
    # Con hora, Notion devuelve milisegundos: se compara el instante, no el texto.
    from datetime import datetime, timezone
    assert p.valor({"type": "date", "date": {"start": "2026-10-18T20:00:00.000+00:00"}}) == datetime(2026, 10, 18, 20, tzinfo=timezone.utc)
    assert p.valor(p.fecha_hora(datetime(2026, 10, 18, 20, tzinfo=timezone.utc))) == datetime(2026, 10, 18, 20, tzinfo=timezone.utc)
    assert p.valor(p.relacion(["3fdb5534-22ec"])) == ["3fdb553422ec"]
    assert p.valor(p.seleccion(None)) is None and p.valor(p.texto(None)) is None


def test_cambios_solo_lo_que_difiere():
    fila = {"id": "x", "properties": {"Km objetivo": p.numero(30), "Tipo": p.seleccion("Base")}}
    assert p.cambios(fila, {"Km objetivo": p.numero(30), "Tipo": p.seleccion("Descarga")}) == {"Tipo": p.seleccion("Descarga")}


def test_textos_largos_se_parten_en_fragmentos():
    assert len(p.texto("a" * 4500)["rich_text"]) == 3
    assert p.valor(p.texto("a" * 4500)) == "a" * 4500


def test_nombres_y_estructura():
    assert t.nombre_semana(1, _micro(date(2026, 10, 19))) == "S1 · 19–25 oct"
    assert t.nombre_semana(2, _micro(date(2026, 10, 26))) == "S2 · 26 oct–1 nov"
    assert t.nombre_sesion(date(2026, 10, 20), "Hill sprints") == "Mar 20/10 · Hill sprints"
    assert t.estructura(SPRINTS) == "Warmup 20' · 6 × (10\" Hill sprints + 2'20\" Rec) · Cooldown 20'"
    assert t.fc_objetivo(ZonasFC.Z1, RANGOS) == "131-148"
    assert t.fc_objetivo(ZonasFC.REC, RANGOS) == "<131"
    assert t.fc_objetivo(ZonasFC.Z3, RANGOS) is None


def test_sesion_a_propiedades():
    props = t.propiedades_sesion(SPRINTS, 1, RANGOS, "semana1")
    assert p.valor(props["Clave"]) == "2026-10-20#1"
    assert p.valor(props["Tipo"]) == "Sprints en cuesta"
    assert p.valor(props["Duración (min)"]) == 55
    assert p.valor(props["Semana"]) == ["semana1"]
    assert p.valor(props["Vigente"]) is True


def test_hecho_suma_las_actividades_del_dia():
    a = SesionRealizada(fecha=date(2026, 10, 20), duracion=timedelta(minutes=30), distancia_km=5, fc_media=140,
                        desnivel_positivo_m=50, rpe=4, sensaciones="Normal")
    b = SesionRealizada(fecha=date(2026, 10, 20), duracion=timedelta(minutes=10), distancia_km=1.5, fc_media=120)
    hecho = t.propiedades_hecho([a, b])
    assert p.valor(hecho["Hecho: duración (min)"]) == 40
    assert p.valor(hecho["Hecho: km"]) == 6.5
    assert p.valor(hecho["Hecho: FC media"]) == 135  # ponderada por duración


FILA_ATLETA = {
    "id": "atleta",
    "properties": {
        "Nombre": p.titulo("Mi ficha"), "Edad": p.numero(31), "Categoría": p.seleccion("1"),
        "AeT (ppm)": p.numero(164), "Método AeT": p.texto("nasal"), "LT (ppm)": p.numero(179),
        "FC máx (ppm)": p.numero(199), "FC reposo (ppm)": p.numero(56), "Fecha umbrales": p.fecha(date(2026, 10, 18)),
        "Máx por día (min)": p.numero(90), "Días sin entrenar": p.multiple(["lunes", "viernes"]),
        "Días largos": p.multiple(["sábado", "domingo"]), "Días largos por semana": p.numero(1),
        "Máx día largo (min)": p.numero(None), "Lesiones": p.texto(None), "Notas": p.texto("Solo running."),
    },
}


def test_ficha_desde_la_fila_de_notion():
    ficha = t.ficha_desde_fila(FILA_ATLETA)
    assert (ficha.edad, ficha.umbrales.fc_aerobico, ficha.umbrales.fc_lactato) == (31, 164, 179)
    assert ficha.disponibilidad.duracion_max_dia == timedelta(minutes=90)
    assert [d.value for d in ficha.disponibilidad.dias_sin_entrenar] == ["lunes", "viernes"]
    assert ficha.disponibilidad.duracion_max_dia_largo is None


def test_ficha_con_un_dato_imposible_no_pasa():
    fila = {"id": "atleta", "properties": dict(FILA_ATLETA["properties"], **{"AeT (ppm)": p.numero(190)})}
    with pytest.raises(ValidationError):
        t.ficha_desde_fila(fila)  # AeT por encima del LT


def test_comentarios_de_la_semana_cerrada_y_observaciones():
    filas = [
        {"properties": {"Fecha": p.fecha(date(2026, 10, 20)), "Comentario": p.texto("Me costaron los sprints.")}},
        {"properties": {"Fecha": p.fecha(date(2026, 10, 27)), "Comentario": p.texto("De la semana siguiente.")}},
        {"properties": {"Fecha": p.fecha(date(2026, 10, 22)), "Comentario": p.texto(None)}},
    ]
    comentarios = t.comentarios_para_ajuste(date(2026, 10, 19), filas, ["Viajo el jueves.", "", "Viajo el jueves."])
    assert comentarios == {"general": "Viajo el jueves.", "por_sesion": [{"fecha": "2026-10-20", "texto": "Me costaron los sprints."}]}
    assert t.comentarios_para_ajuste(date(2026, 10, 19), [], [None]) is None
