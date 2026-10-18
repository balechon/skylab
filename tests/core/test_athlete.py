from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from core.athlete import DiaSemana, Disponibilidad, FichaAtleta, Umbrales, revisar_disponibilidad
from core.training import (
    ClaseSesion,
    Mesociclo,
    ObjetivosMicrociclo,
    Microciclo,
    ModoPlan,
    ObjetivoMesociclo,
    Plan,
    SesionPlanificada,
    TipoMicrociclo,
    TipoSesion,
    ZonasFC,
)

LUNES = date(2026, 10, 19)

# Entre semana hasta 1:30; sábado o domingo, uno de los dos, sin límite.
DISPONIBILIDAD = Disponibilidad(
    duracion_max_dia=timedelta(minutes=90),
    dias_largos=[DiaSemana.SABADO, DiaSemana.DOMINGO],
    dias_largos_por_semana=1,
)


def _sesion(dia: int, minutos: int, clase=ClaseSesion.FONDO) -> SesionPlanificada:
    if clase == ClaseSesion.DESCANSO:
        return SesionPlanificada(fecha=LUNES + timedelta(days=dia), clase_sesion=clase)
    return SesionPlanificada(
        fecha=LUNES + timedelta(days=dia),
        clase_sesion=clase,
        tipo_sesion=TipoSesion.BASE,
        duracion_objetivo=timedelta(minutes=minutos),
        zona_fc_objetivo=ZonasFC.Z1,
    )


def _plan(*sesiones: SesionPlanificada, lunes: date = LUNES) -> Plan:
    micro = Microciclo(
        fecha_inicio=lunes,
        fecha_fin=lunes + timedelta(days=6),
        tipo_microciclo=TipoMicrociclo.CARGA,
        objetivos=ObjetivosMicrociclo(duracion=timedelta(hours=6)),
        sesiones=list(sesiones),
    )
    return Plan(
        modo=ModoPlan.CONSTRUCCION,
        fecha_inicio=lunes,
        fecha_objetivo=lunes + timedelta(days=6),
        mesociclos=[
            Mesociclo(
                objetivo=ObjetivoMesociclo.BASE_AEROBICA,
                fecha_inicio=lunes,
                fecha_fin=lunes + timedelta(days=6),
                microciclos=[micro],
            )
        ],
    )


def test_una_semana_que_cabe_no_tiene_problemas():
    plan = _plan(_sesion(0, 0, ClaseSesion.DESCANSO), _sesion(1, 60), _sesion(3, 90), _sesion(5, 60), _sesion(6, 210))
    assert revisar_disponibilidad(plan, DISPONIBILIDAD, LUNES) == []


def test_entre_semana_no_puede_pasar_del_maximo():
    problemas = revisar_disponibilidad(_plan(_sesion(2, 100)), DISPONIBILIDAD, LUNES)
    assert problemas == [f"El miércoles {LUNES + timedelta(days=2)} suma 1:40 y el atleta puede como mucho 1:30."]


def test_la_duracion_se_suma_por_dia():
    # Dos sesiones el mismo martes: 60 + 45 = 1:45.
    problemas = revisar_disponibilidad(_plan(_sesion(1, 60), _sesion(1, 45)), DISPONIBILIDAD, LUNES)
    assert len(problemas) == 1 and "1:45" in problemas[0]


def test_solo_un_dia_largo_por_semana():
    problemas = revisar_disponibilidad(_plan(_sesion(5, 180), _sesion(6, 150)), DISPONIBILIDAD, LUNES)
    assert len(problemas) == 1
    assert "2 días de más de 1:30" in problemas[0] and "solo puede 1 por semana" in problemas[0]


def test_dia_sin_entrenar():
    disponibilidad = DISPONIBILIDAD.model_copy(update={"dias_sin_entrenar": [DiaSemana.LUNES]})
    problemas = revisar_disponibilidad(_plan(_sesion(0, 30)), disponibilidad, LUNES)
    assert problemas == [f"El lunes {LUNES} el atleta no puede entrenar y el plan pone sesión."]
    # Un descanso planificado ese día no es un problema.
    assert revisar_disponibilidad(_plan(_sesion(0, 0, ClaseSesion.DESCANSO)), disponibilidad, LUNES) == []


def test_tope_del_dia_largo():
    disponibilidad = DISPONIBILIDAD.model_copy(update={"duracion_max_dia_largo": timedelta(hours=4)})
    problemas = revisar_disponibilidad(_plan(_sesion(6, 270)), disponibilidad, LUNES)
    assert problemas == [f"El domingo {LUNES + timedelta(days=6)} suma 4:30 y en un día largo puede como mucho 4:00."]


def test_cada_sesion_necesita_duracion():
    sin_duracion = SesionPlanificada(
        fecha=LUNES + timedelta(days=1), clase_sesion=ClaseSesion.FONDO, tipo_sesion=TipoSesion.BASE, distancia_objetivo_km=8
    )
    problemas = revisar_disponibilidad(_plan(sin_duracion), DISPONIBILIDAD, LUNES)
    assert problemas == [f"La sesión del {LUNES + timedelta(days=1)} no tiene duracion_objetivo: hace falta para comprobar la disponibilidad."]


def test_las_semanas_pasadas_no_se_revisan():
    plan = _plan(_sesion(2, 120))
    assert revisar_disponibilidad(plan, DISPONIBILIDAD, LUNES + timedelta(days=7)) == []


def test_umbrales_en_orden():
    Umbrales(fc_reposo=50, fc_aerobico=149, fc_lactato=170, fc_maxima=190)
    with pytest.raises(ValidationError, match="reposo < aeróbico < lactato < máxima"):
        Umbrales(fc_aerobico=170, fc_lactato=149)


def test_disponibilidad_coherente():
    with pytest.raises(ValidationError, match="libre y día largo"):
        Disponibilidad(duracion_max_dia=timedelta(hours=1), dias_sin_entrenar=[DiaSemana.SABADO], dias_largos=[DiaSemana.SABADO])
    with pytest.raises(ValidationError, match="dias_largos_por_semana"):
        Disponibilidad(duracion_max_dia=timedelta(hours=1), dias_largos=[DiaSemana.SABADO], dias_largos_por_semana=2)


def test_ficha_desde_json():
    ficha = FichaAtleta.model_validate(
        {
            "edad": 31,
            "categoria": "1",
            "umbrales": {"fc_aerobico": 149, "metodo_aerobico": "MAF (180 − edad)"},
            "disponibilidad": {
                "duracion_max_dia": "PT1H30M",
                "dias_largos": ["sábado", "domingo"],
                "dias_largos_por_semana": 1,
            },
        }
    )
    assert ficha.disponibilidad.duracion_max_dia == timedelta(minutes=90)
    assert ficha.disponibilidad.dias_largos == [DiaSemana.SABADO, DiaSemana.DOMINGO]


# ---------- pulsaciones por zona ----------

from core.methodology import DefinicionZonas  # noqa: E402
from core.athlete import rangos_fc  # noqa: E402

ZONAS_UA = DefinicionZonas.model_validate(
    {
        "id": "UA-ZONAS-001",
        "descripcion": "Zonas por umbrales.",
        "zonas": {
            "Z1": {"desde": {"ancla": "AeT", "pct": -20}, "hasta": {"ancla": "AeT", "pct": -10}},
            "Z2": {"desde": {"ancla": "AeT", "pct": -10}, "hasta": {"ancla": "AeT"}},
            "Z3": {"desde": {"ancla": "AeT"}, "hasta": {"ancla": "LT"}},
            "Z4": {"desde": {"ancla": "LT"}, "hasta": {"ancla": "FCmax"}},
        },
    }
)


def test_con_solo_el_aet_salen_z1_y_z2():
    rangos = rangos_fc(ZONAS_UA, Umbrales(fc_aerobico=149))
    assert {z.value: (r.minimo, r.maximo) for z, r in rangos.items()} == {"Z1": (119, 134), "Z2": (134, 149)}


def test_con_todos_los_umbrales_salen_hasta_z4():
    rangos = rangos_fc(ZONAS_UA, Umbrales(fc_aerobico=149, fc_lactato=170, fc_maxima=192))
    assert (rangos[ZonasFC.Z3].minimo, rangos[ZonasFC.Z3].maximo) == (149, 170)
    assert (rangos[ZonasFC.Z4].minimo, rangos[ZonasFC.Z4].maximo) == (170, 192)


def test_sin_definicion_de_zonas_no_hay_rangos():
    assert rangos_fc(None, Umbrales(fc_aerobico=149)) == {}
