# Un ciclo del servicio de Notion. Se repite cada pocos minutos:
#
#   1. Ficha: si la fila del atleta cambió, se envía a la API (PUT /atleta).
#   2. Peticiones: las semanas con Evaluar o Recalcular marcado lanzan el
#      ajuste semanal con los comentarios del atleta; el feedback se escribe
#      en la semana evaluada y la semana nueva se publica en el reloj.
#   3. Plan: las semanas y las sesiones del plan vigente se vuelcan a Notion
#      (se crean o se actualizan; nunca se borran).
#   4. Realizado: lo que trajo Garmin se escribe en las columnas "Hecho".
#
# Nada depende de las horas de edición de Notion: las peticiones son casillas
# que el servicio desmarca al atenderlas, y la ficha se compara con la que
# tiene la API. Lo que escribe el servicio nunca dispara nada.

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional, Protocol

from pydantic import ValidationError

from core.athlete import FichaAtleta
from core.training import Plan, SesionRealizada
from notion import propiedades as p
from notion import traduccion as t
from notion.clientes import RespuestaSkylab

log = logging.getLogger("skylab.notion")


class Notion(Protocol):
    async def consultar(self, data_source_id: str, filtro: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]: ...
    async def crear(self, data_source_id: str, propiedades: dict[str, Any]) -> dict[str, Any]: ...
    async def actualizar(self, page_id: str, propiedades: dict[str, Any]) -> None: ...


class Skylab(Protocol):
    async def atleta(self) -> RespuestaSkylab: ...
    async def guardar_atleta(self, ficha: dict[str, Any]) -> RespuestaSkylab: ...
    async def plan(self) -> RespuestaSkylab: ...
    async def sesiones(self, desde: date, hasta: date) -> RespuestaSkylab: ...
    async def monitor(self) -> RespuestaSkylab: ...
    async def ajustar(self, comentarios: Optional[dict[str, Any]], forzar: bool) -> RespuestaSkylab: ...
    async def sincronizar(self) -> RespuestaSkylab: ...
    async def publicar(self) -> RespuestaSkylab: ...


@dataclass
class ResumenCiclo:
    ficha_enviada: bool = False
    peticiones: list[str] = field(default_factory=list)
    filas_creadas: int = 0
    filas_actualizadas: int = 0
    avisos: list[str] = field(default_factory=list)


PETICIONES = {"or": [{"property": "Evaluar", "checkbox": {"equals": True}}, {"property": "Recalcular", "checkbox": {"equals": True}}]}


def lunes(dia: date) -> date:
    return dia - timedelta(days=dia.weekday())


class ServicioNotion:
    def __init__(
        self,
        notion: Notion,
        skylab: Skylab,
        ds_atleta: str,
        ds_semanas: str,
        ds_entrenamientos: str,
        hoy: Callable[[], date] = date.today,
        sync_cada_ciclos: int = 10,
        ds_resumen: str = "",
        ds_ejecuciones: str = "",
        ds_carga: str = "",
        ahora: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ):
        self.notion = notion
        self.skylab = skylab
        self.ds_atleta = ds_atleta
        self.ds_semanas = ds_semanas
        self.ds_entrenamientos = ds_entrenamientos
        self.hoy = hoy
        self.sync_cada_ciclos = sync_cada_ciclos
        self.ds_resumen, self.ds_ejecuciones, self.ds_carga = ds_resumen, ds_ejecuciones, ds_carga
        self.ahora = ahora
        self._ciclos = 0

    async def ciclo(self) -> ResumenCiclo:
        resumen = ResumenCiclo()
        # Garmin no se consulta en cada ciclo: lo hecho aparece en Notion con
        # unos minutos de retraso, y antes de cada ajuste se sincroniza igual.
        if self._ciclos % self.sync_cada_ciclos == 0:
            sync = await self.skylab.sincronizar()
            if not sync.ok:
                resumen.avisos.append(f"Sync de Garmin: {sync.detalle}")
        self._ciclos += 1
        await self.sincronizar_ficha(resumen)
        await self.atender_peticiones(resumen)
        await self.volcar_plan(resumen)
        if self.ds_resumen and self.ds_ejecuciones and self.ds_carga:
            await self.volcar_monitor(resumen)
        return resumen

    # ---------- 5. monitor ----------

    async def volcar_monitor(self, resumen: ResumenCiclo) -> None:
        """La capa gold (coste y rendimiento del agente, carga semanal) en la
        página Monitor, y el estado del servicio."""
        respuesta = await self.skylab.monitor()
        if not respuesta.ok:
            resumen.avisos.append(f"Monitor: {respuesta.detalle}")
            return
        gold = respuesta.cuerpo
        for ds, filas, traducir, clave in (
            (self.ds_ejecuciones, gold["ejecuciones"], t.propiedades_ejecucion, lambda e: str(e["id"])),
            (self.ds_carga, gold["semanas"], t.propiedades_carga, lambda s: s["semana"]),
        ):
            existentes = {p.leer(f, "Clave"): f for f in await self.notion.consultar(ds)}
            for fila in filas:
                await self._guardar(ds, existentes.get(clave(fila)), traducir(fila), resumen)

        total = {p.leer(f, "Clave"): f for f in await self.notion.consultar(self.ds_resumen)}.get("total")
        deseadas = t.propiedades_resumen(gold["resumen"], self.ahora(), resumen.avisos)
        await self._guardar(self.ds_resumen, total, deseadas, resumen)

    # ---------- 1. ficha ----------

    async def sincronizar_ficha(self, resumen: ResumenCiclo) -> None:
        filas = await self.notion.consultar(self.ds_atleta)
        if not filas:
            return
        fila = filas[0]
        try:
            ficha = t.ficha_desde_fila(fila)
        except ValidationError as error:
            dato = error.errors()[0]
            aviso = f"Ficha no válida ({'.'.join(str(x) for x in dato['loc'])}): {dato['msg']}"
            resumen.avisos.append(aviso)
            await self._mensaje(fila, aviso)
            return
        actual = await self.skylab.atleta()
        if actual.ok and FichaAtleta.model_validate(actual.cuerpo) == ficha:
            return
        respuesta = await self.skylab.guardar_atleta(ficha.model_dump(mode="json"))
        if respuesta.ok:
            resumen.ficha_enviada = True
            await self._mensaje(fila, f"Ficha enviada el {self.hoy():%d/%m}.")
        else:
            aviso = f"La API rechazó la ficha: {respuesta.detalle}"
            resumen.avisos.append(aviso)
            await self._mensaje(fila, aviso)

    async def _mensaje(self, fila: dict[str, Any], mensaje: str) -> None:
        cambios = p.cambios(fila, {"Mensaje SKYLAB": p.texto(mensaje)})
        if cambios:
            await self.notion.actualizar(fila["id"], cambios)

    # ---------- 2. Evaluar / Recalcular ----------

    async def atender_peticiones(self, resumen: ResumenCiclo) -> None:
        marcadas = [
            f
            for f in await self.notion.consultar(self.ds_semanas, PETICIONES)
            if p.leer(f, "Evaluar") or p.leer(f, "Recalcular")
        ]
        # Una sola por ciclo: cada una puede llamar al modelo.
        if marcadas:
            await self._atender(min(marcadas, key=lambda f: p.leer(f, "Inicio") or date.max), resumen)

    async def _atender(self, fila: dict[str, Any], resumen: ResumenCiclo) -> None:
        hoy = self.hoy()
        recalcular = bool(p.leer(fila, "Recalcular"))
        inicio = p.leer(fila, "Inicio")
        semana_cerrada = lunes(hoy) - timedelta(days=7)
        if not recalcular and inicio and inicio + timedelta(days=6) >= hoy:
            mensaje = "Esta semana aún no ha terminado: se puede evaluar a partir del lunes."
            resumen.peticiones.append(mensaje)
            await self.notion.actualizar(fila["id"], t.propiedades_fin_de_peticion(mensaje))
            return

        semanas = await self.notion.consultar(self.ds_semanas)
        observaciones = [p.leer(fila, "Observaciones")] + [
            p.leer(s, "Observaciones") for s in semanas if p.leer(s, "Inicio") == lunes(hoy)
        ]
        sesiones = await self.notion.consultar(self.ds_entrenamientos)
        comentarios = t.comentarios_para_ajuste(semana_cerrada, sesiones, observaciones)

        await self.skylab.sincronizar()  # que el ajuste vea lo último de Garmin
        respuesta = await self.skylab.ajustar(comentarios, forzar=recalcular)
        if not respuesta.ok:
            mensaje = f"No se ajustó: {respuesta.detalle}"
            resumen.peticiones.append(mensaje)
            await self.notion.actualizar(fila["id"], t.propiedades_fin_de_peticion(mensaje))
            return

        cuerpo = respuesta.cuerpo if isinstance(respuesta.cuerpo, dict) else {}
        version = cuerpo.get("version")
        if cuerpo.get("estado") not in (None, "plan_valido"):
            mensaje = f"El agente no produjo un plan válido ({cuerpo.get('estado')}): {cuerpo.get('resumen') or cuerpo.get('detalle')}"
        else:
            mensaje = f"Ajuste hecho: plan v{version}." if version else "Ajuste lanzado."
            if version:
                publicacion = await self.skylab.publicar()
                mensaje += " Semana publicada en el reloj." if publicacion.ok else f" No se publicó: {publicacion.detalle}"
        resumen.peticiones.append(mensaje)

        await self.notion.actualizar(fila["id"], t.propiedades_fin_de_peticion(mensaje))
        feedback = cuerpo.get("feedback")
        if feedback:
            evaluada = next((s for s in semanas if p.leer(s, "Inicio") == semana_cerrada), None)
            if evaluada is not None:
                await self.notion.actualizar(evaluada["id"], t.propiedades_feedback(feedback, mensaje))

    # ---------- 3 y 4. plan y realizado ----------

    async def volcar_plan(self, resumen: ResumenCiclo) -> None:
        respuesta = await self.skylab.plan()
        if not respuesta.ok:
            return
        plan = Plan.model_validate(respuesta.cuerpo["plan"])
        version = respuesta.cuerpo["version"]

        semanas = await self.notion.consultar(self.ds_semanas)
        por_clave = {p.leer(s, "Clave"): s for s in semanas if p.leer(s, "Clave")}
        por_inicio = {p.leer(s, "Inicio"): s for s in semanas if not p.leer(s, "Clave")}
        id_semana: dict[date, str] = {}
        numero = 0
        for meso in plan.mesociclos:
            for micro in meso.microciclos:
                numero += 1
                deseadas = t.propiedades_semana(numero, micro, meso, version)
                fila = por_clave.get(t.clave_semana(micro)) or por_inicio.get(micro.fecha_inicio)
                id_semana[micro.fecha_inicio] = await self._guardar(
                    self.ds_semanas, fila, deseadas, resumen, al_crear={"Estado": p.seleccion("Planificada")}
                )

        sesiones = await self.notion.consultar(self.ds_entrenamientos)
        por_clave = {p.leer(s, "Clave"): s for s in sesiones if p.leer(s, "Clave")}
        sin_clave: dict[date, list[dict[str, Any]]] = {}
        for s in sesiones:
            if not p.leer(s, "Clave") and p.leer(s, "Fecha"):
                sin_clave.setdefault(p.leer(s, "Fecha"), []).append(s)

        vigentes: set[str] = set()
        planificadas: dict[date, list[dict[str, Any]]] = {}
        for meso in plan.mesociclos:
            for micro in meso.microciclos:
                for orden, sesion in t.sesiones_con_orden(micro):
                    clave = t.clave_sesion(sesion.fecha, orden)
                    vigentes.add(clave)
                    fila = por_clave.get(clave)
                    if fila is None and sin_clave.get(sesion.fecha):
                        fila = sin_clave[sesion.fecha].pop(0)  # fila creada a mano: se adopta
                    deseadas = t.propiedades_sesion(sesion, orden, plan.rangos_fc, id_semana.get(micro.fecha_inicio))
                    page_id = await self._guardar(self.ds_entrenamientos, fila, deseadas, resumen)
                    planificadas.setdefault(sesion.fecha, []).append({"id": page_id, "fila": fila})

        # Sesiones que ya no están en el plan: se conservan, desmarcadas.
        for clave, fila in por_clave.items():
            if t.es_clave_de_sesion(clave) and clave not in vigentes and p.leer(fila, "Vigente"):
                await self.notion.actualizar(fila["id"], {"Vigente": p.casilla(False)})
                resumen.filas_actualizadas += 1

        await self.volcar_realizado(plan, planificadas, por_clave, id_semana, resumen)

    async def volcar_realizado(
        self,
        plan: Plan,
        planificadas: dict[date, list[dict[str, Any]]],
        por_clave: dict[str, dict[str, Any]],
        id_semana: dict[date, str],
        resumen: ResumenCiclo,
    ) -> None:
        hoy = self.hoy()
        if plan.fecha_inicio > hoy:
            return
        respuesta = await self.skylab.sesiones(plan.fecha_inicio, hoy)
        if not respuesta.ok:
            return
        por_dia: dict[date, list[SesionRealizada]] = {}
        for crudo in respuesta.cuerpo:
            actividad = SesionRealizada.model_validate(crudo)
            por_dia.setdefault(actividad.fecha, []).append(actividad)

        for dia, actividades in sorted(por_dia.items()):
            filas = planificadas.get(dia, [])
            if filas:
                # El día tenía sesión planificada: lo hecho va en su fila
                # (varias actividades el mismo día se suman).
                destino = filas[0]
                await self._guardar(self.ds_entrenamientos, destino["fila"], t.propiedades_hecho(actividades), resumen,
                                    page_id=destino["id"])
                continue
            for actividad in actividades:
                if actividad.garmin_activity_id is None:
                    continue
                fila = por_clave.get(t.clave_actividad(actividad.garmin_activity_id))
                deseadas = t.propiedades_actividad_extra(actividad, id_semana.get(lunes(dia))) | t.propiedades_hecho([actividad])
                await self._guardar(self.ds_entrenamientos, fila, deseadas, resumen)

    async def _guardar(
        self,
        data_source_id: str,
        fila: Optional[dict[str, Any]],
        deseadas: dict[str, Any],
        resumen: ResumenCiclo,
        al_crear: Optional[dict[str, Any]] = None,
        page_id: Optional[str] = None,
    ) -> str:
        """Crea la fila o actualiza solo lo que cambió. Devuelve su id."""
        if fila is None and page_id is None:
            creada = await self.notion.crear(data_source_id, deseadas | (al_crear or {}))
            resumen.filas_creadas += 1
            return t.sin_guiones(creada["id"])
        cambios = p.cambios(fila, deseadas)
        destino = page_id or t.sin_guiones(fila["id"])
        if cambios:
            await self.notion.actualizar(destino, cambios)
            resumen.filas_actualizadas += 1
        return destino
