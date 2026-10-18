# Guardia final: código, no LLM. Revisa el resultado que entrega el agente
# antes de aceptarlo. Si encuentra problemas, se los devuelve al agente para
# que corrija; nada se guarda hasta que la guardia no tenga objeciones.
#
# Es lo que convierte "nunca inventa metodología" en una garantía: el plan
# vuelve a pasar por el validador, cada regla citada debe existir en el
# perfil, la acción de ajuste debe ser la que decidió el motor y las semanas
# pasadas no se tocan.

from agent.esquemas import ContextoAgente, EstadoResultado, Operacion, ResultadoAgente
from datetime import timedelta

from core.athlete import revisar_disponibilidad
from core.training import Mesociclo, Microciclo, Plan
from core.validator import validar_plan

_MAX_VIOLACIONES_LISTADAS = 10


def _microciclos(plan: Plan) -> list[Microciclo]:
    return [micro for meso in plan.mesociclos for micro in meso.microciclos]


def revisar_resultado(resultado: ResultadoAgente, ctx: ContextoAgente) -> list[str]:
    """Lista de problemas; vacía si el resultado se puede aceptar."""
    problemas: list[str] = []

    ids = set(ctx.perfil.todos_los_ids())
    citados = {rid for j in resultado.justificaciones for rid in j.regla_ids}
    citados |= {v.regla_id for v in resultado.violaciones}
    if resultado.feedback is not None:
        citados |= {c.regla_id for c in resultado.feedback.consejos if c.regla_id}
    inventados = sorted(citados - ids)
    if inventados:
        problemas.append(f"Cita reglas que no existen en el perfil: {inventados}.")

    if resultado.estado == EstadoResultado.SIN_SOLUCION:
        return problemas

    plan = resultado.plan
    validacion = validar_plan(plan, ctx.perfil)
    for v in validacion.violaciones[:_MAX_VIOLACIONES_LISTADAS]:
        problemas.append(f"Violación de {v.regla_id}: {v.mensaje}")
    if len(validacion.violaciones) > _MAX_VIOLACIONES_LISTADAS:
        problemas.append(f"... y {len(validacion.violaciones) - _MAX_VIOLACIONES_LISTADAS} violaciones más.")

    problemas += _revisar_secuencia_bloques(resultado, plan, ctx)

    if ctx.operacion == Operacion.CREAR_CICLO:
        problemas += _revisar_ciclo_nuevo(plan, ctx)
    else:
        problemas += _revisar_ajuste(resultado, plan, ctx)

    proxima = next((m for m in _microciclos(plan) if m.fecha_fin >= ctx.hoy), None)
    if proxima is None:
        problemas.append(f"El plan no tiene ningún microciclo desde {ctx.hoy}.")
    elif not proxima.detallado:
        problemas.append(
            f"La semana del {proxima.fecha_inicio} es la próxima y debe tener sesiones concretas (nivel 1)."
        )
    problemas += _revisar_bloque_actual(plan, ctx)
    if ctx.atleta is not None and ctx.atleta.disponibilidad is not None:
        problemas += [
            f"Disponibilidad: {p}" for p in revisar_disponibilidad(plan, ctx.atleta.disponibilidad, ctx.hoy)
        ][:_MAX_VIOLACIONES_LISTADAS]
    return problemas


def _revisar_bloque_actual(plan: Plan, ctx: ContextoAgente) -> list[str]:
    """El mesociclo en curso debe tener todas sus semanas definidas (nivel 2
    como mínimo), sin huecos, de su primer a su último día. Así, al entrar en
    un bloque nuevo, deja de ser esqueleto. Los bloques futuros pueden seguir
    siendo esqueleto (nivel 3)."""
    actual: Mesociclo | None = next((m for m in plan.mesociclos if m.fecha_fin >= ctx.hoy), None)
    if actual is None:
        return []
    if not actual.microciclos:
        return [
            f"El bloque en curso ({actual.objetivo.value}, {actual.fecha_inicio} – {actual.fecha_fin}) "
            "es solo esqueleto: debe tener sus semanas con objetivos (nivel 2)."
        ]
    problemas = []
    esperado = actual.fecha_inicio
    for micro in actual.microciclos:
        if micro.fecha_inicio != esperado:
            problemas.append(
                f"El bloque {actual.objetivo.value} no tiene semanas definidas entre {esperado} y "
                f"{micro.fecha_inicio - timedelta(days=1)}."
            )
        esperado = micro.fecha_fin + timedelta(days=1)
    if esperado <= actual.fecha_fin:
        problemas.append(
            f"El bloque {actual.objetivo.value} no tiene semanas definidas entre {esperado} y {actual.fecha_fin}."
        )
    return problemas


def _revisar_secuencia_bloques(resultado: ResultadoAgente, plan: Plan, ctx: ContextoAgente) -> list[str]:
    """Los objetivos de los mesociclos los fija el perfil. Sin secuencia para
    el modo del plan no hay forma de elegirlos sin inventar: se rechaza."""
    secuencia = ctx.perfil.secuencia_para(plan.modo)
    if secuencia is None:
        return [
            f"El perfil no define la secuencia de bloques para el modo {plan.modo.value}: "
            "los objetivos de los mesociclos no se pueden elegir sin inventar metodología."
        ]
    citadas = {rid for j in resultado.justificaciones for rid in j.regla_ids}
    if secuencia.id not in citadas:
        return [f"Los objetivos de los mesociclos deben justificarse citando {secuencia.id}."]
    return []


def _revisar_ciclo_nuevo(plan: Plan, ctx: ContextoAgente) -> list[str]:
    problemas = []
    solicitud = ctx.solicitud
    if plan.version != 1:
        problemas.append(f"Un ciclo nuevo empieza en la versión 1, no en la {plan.version}.")
    if plan.modo != solicitud.modo:
        problemas.append(f"Se pidió modo {solicitud.modo.value} y el plan es {plan.modo.value}.")
    if plan.fecha_objetivo != solicitud.fecha_objetivo:
        problemas.append(f"Se pidió fecha objetivo {solicitud.fecha_objetivo} y el plan tiene {plan.fecha_objetivo}.")
    if plan.carrera != solicitud.carrera:
        problemas.append("La carrera del plan no coincide con la solicitada.")
    return problemas


def _revisar_ajuste(resultado: ResultadoAgente, plan: Plan, ctx: ContextoAgente) -> list[str]:
    problemas = []
    vigente = ctx.plan_vigente

    if plan.version != vigente.version + 1:
        problemas.append(f"El ajuste debe ser la versión {vigente.version + 1}, no la {plan.version}.")
    for campo in ("modo", "fecha_inicio", "fecha_objetivo", "carrera"):
        if getattr(plan, campo) != getattr(vigente, campo):
            problemas.append(f"Un ajuste semanal no puede cambiar {campo}.")

    nuevos = {m.fecha_inicio: m for m in _microciclos(plan)}
    for pasado in (m for m in _microciclos(vigente) if m.fecha_fin < ctx.hoy):
        if nuevos.get(pasado.fecha_inicio) != pasado:
            problemas.append(f"La semana del {pasado.fecha_inicio} ya pasó y no puede modificarse.")

    accion = ctx.evaluacion.accion if ctx.evaluacion else None
    if accion is not None:
        citadas = {rid for j in resultado.justificaciones for rid in j.regla_ids}
        if accion.regla_id not in citadas:
            problemas.append(
                f"El motor decidió {accion.accion.value} por {accion.regla_id}; "
                "el plan debe aplicarla y citar esa regla."
            )

    # El feedback cierra la semana para el atleta: obligatorio, y si el motor
    # decidió una acción, la explicación debe nombrar la regla que la causó.
    if ctx.evaluacion is not None:
        if resultado.feedback is None:
            problemas.append("El ajuste semanal necesita el feedback de la semana para el atleta.")
        elif accion is not None and accion.regla_id not in resultado.feedback.por_que_cambia:
            problemas.append(
                f"feedback.por_que_cambia debe explicar la acción {accion.accion.value} citando {accion.regla_id}."
            )
    return problemas
