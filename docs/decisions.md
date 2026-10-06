# Decisiones de arquitectura

Registro breve (ADR-lite) de las decisiones tomadas y su motivo. Añadir una
entrada nueva cuando se tome una decisión de arquitectura relevante.

## 2026-08-18 — Motor híbrido: determinista + LLM

**Decisión**: el cálculo de carga/volumen/intensidad, la validación de
restricciones y la detección de desviación son deterministas (Python,
testeados). El LLM compone la rutina, evalúa progreso y redacta
justificaciones, pero siempre propone dentro del espacio que el motor
determinista valida — nunca es el árbitro de si algo cumple la metodología.

**Por qué**: el objetivo del proyecto exige que el sistema "nunca invente
metodología" y que "si no puede cumplir las restricciones, lo diga". Un LLM
puro puede alucinar reglas o forzar una solución "bonita" ante un conflicto
irresoluble. Separar el árbitro (determinista) del proponente (LLM) hace
que esa garantía sea verificable con tests, no solo una instrucción de
prompt.

## 2026-08-18 — Un perfil de metodología activo por plan

**Decisión**: cada plan usa un único perfil YAML (`methodology/profiles/`)
de un autor/framework. No se combinan reglas de distintos autores dentro
de un mismo plan.

**Por qué**: mezclar reglas de metodologías distintas puede generar
conflictos no resolubles sin criterio arbitrario. Mantener un perfil activo
por plan simplifica la validación y hace que cada regla citada sea
inequívocamente atribuible a una fuente.

## 2026-08-18 — Transcripción manual de metodología a YAML

**Decisión**: los perfiles de metodología se transcriben a mano por el
usuario a partir de la fuente original (libro, paper, apuntes), no por el
LLM.

**Por qué**: es el punto de mayor riesgo de que el sistema "invente"
metodología. Transcripción manual garantiza que cada regla en el sistema
existe porque un humano la verificó contra la fuente.

## 2026-08-18 — MCP como cliente, no como servidor

> **Actualizada (2026-10-06)**: se mantiene "MCP como cliente", pero el
> servidor es `garmin-mcp`, no Strava. Ver la entrada "Datos de Garmin vía
> garmin_mcp" más abajo.

**Decisión**: el agente consume servidores MCP externos (ej. un MCP de
Strava) en vez de exponer su propio servidor MCP.

**Por qué**: el objetivo de aprendizaje incluye MCP como consumidor;
además el historial de entrenamiento ya vive en sistemas externos (Strava),
así que consumir su MCP es el camino más directo. Exponer un servidor MCP
propio queda abierto como posible extensión futura, no descartado.

## 2026-08-18 — n8n como orquestador del flujo completo

**Decisión**: n8n dispara el proceso (cron/webhook), invoca al agente y
gestiona notificaciones del resultado, en vez de limitarse a sincronizar
datos de Strava.

**Por qué**: mantiene la lógica de negocio (motor + agente) dentro del
proyecto Python, testeable y versionada, mientras n8n se ocupa de lo que
mejor hace: orquestación de flujo y notificaciones, sin lógica de dominio
dentro de los workflows.

## 2026-10-06 — Alcance: uso personal, un solo usuario

**Decisión**: el sistema es para un único usuario (el autor). Sin interfaz
web, sin cuentas, sin multi-tenant. Visión completa en `docs/vision.md`.

**Por qué**: el objetivo es un coach personal útil, no un producto. Quitar
usuarios, autenticación y UI elimina la mayor parte de la complejidad de
despliegue y deja el esfuerzo en lo diferencial (metodología + motor).

## 2026-10-06 — Dos modos de plan: construcción y competición

**Decisión**: `Plan` tiene un `modo`. *Construcción* planifica hacia adelante
hasta una fecha de corte, sin carrera, buscando subir el techo de forma
progresiva. *Competición* planifica hacia atrás desde una carrera. La
transición entre modos la rigen reglas del perfil.

**Por qué**: es el diferencial del proyecto frente a planes genéricos, que
casi siempre anclan todo a una carrera. Hasta fin de 2026 se usa
construcción (base y fuerza); en 2027, competición.

## 2026-10-06 — Planificación rodante con tres niveles de detalle

**Decisión**: se genera el ciclo completo una vez y se ajusta cada semana.
El detalle baja con la distancia: próxima semana en sesiones concretas,
resto del mesociclo en objetivos semanales, mesociclos futuros como
esqueleto. Las semanas pasadas se congelan y cada ajuste crea una versión
nueva del plan.

**Por qué**: detallar sesiones lejanas es trabajo que el propio ajuste
semanal va a descartar. Además acota el contexto del ajuste semanal (menos
tokens) y refleja cómo planifica un entrenador real.

**Consecuencias en `domain/`**: separar sesión planificada de sesión
realizada; permitir microciclos con objetivos y sin sesiones; versionar
el plan.

## 2026-10-06 — Evaluación semanal en dos ejes: adherencia y progreso

**Decisión**: el ajuste semanal mide adherencia (¿cumplí el plan?) y
progreso (¿me estoy adaptando?) por separado. El progreso sale de tests de
control al final de cada mesociclo e indicadores pasivos calculados desde
sesiones en llano (o ritmo ajustado por desnivel).

**Por qué**: el modo construcción no tiene carrera que marque el éxito; sin
un indicador de progreso el sistema no puede decidir si progresar, repetir
o extender un bloque.

## 2026-10-06 — Reglas de ajuste en el perfil: condición → acción

**Decisión**: el perfil YAML gana un tipo de regla `reglas_ajuste`
(condición sobre métricas de adherencia/progreso → acción). Las acciones
son un Enum cerrado; el motor decide qué acción aplica y el LLM solo la
concreta. Los umbrales y cambios de carga se expresan en porcentajes
relativos a la línea base del atleta. Cada regla declara `origen`:
`autor` o `propio`.

**Por qué**: sin reglas de ajuste explícitas, la reacción a un desvío la
inventaría el LLM, rompiendo el principio central. Los porcentajes son como
suelen expresarse los autores y adaptan el mismo perfil al atleta sin
reescribirlo. `origen` deja trazado qué es del autor y qué es interpretación
propia de una indicación cualitativa.

## 2026-10-06 — API HTTP mínima + docker-compose con n8n

**Decisión**: `pb-coach` expone una API HTTP mínima (`POST /plan`,
`POST /semana/ajustar`) y corre en Docker junto a n8n en un mismo host vía
`docker-compose`. No se expone a internet; solo n8n la llama, con un token
compartido.

**Por qué**: n8n vive en otro contenedor, así que HTTP es la forma limpia de
invocarlo. Mantenerlo interno evita tener que endurecer un servicio público.

## 2026-10-06 — Persistencia en SQLite

> **Reemplazada (2026-10-06)** por "Postgres para pb-coach y n8n", más abajo.

**Decisión**: SQLite en un volumen de Docker para planes versionados,
sesiones realizadas y registro de ejecuciones del agente (incluido el
consumo de tokens). Los perfiles de metodología siguen en YAML en git.

**Por qué**: la planificación rodante necesita recordar el plan vigente y
su historial entre semanas. Con un solo usuario y una ejecución semanal, un
servidor de base de datos (Postgres) es complejidad sin beneficio.

## 2026-10-06 — Datos de Garmin vía garmin_mcp; Strava descartado

**Decisión**: las actividades se leen de Garmin Connect, y los
entrenamientos de la próxima semana se publican en el reloj, a través de
[Taxuspt/garmin_mcp](https://github.com/Taxuspt/garmin_mcp) corriendo como
contenedor propio (`garmin-mcp`) en el docker-compose, con versión fijada.
`pb-coach` es su cliente MCP (`mcp_client/garmin.py`) y solo usa una lista
blanca de tools. El LLM nunca ve ese servidor: la lectura (sync → base de datos) y
la escritura (publicar la semana) son pasos deterministas fuera del bucle
del agente. Las sesiones de running se publican generando el JSON del
entrenamiento desde código; si el formato se queda corto, plan B para la
escritura: [st3v/garmin-workouts-mcp](https://github.com/st3v/garmin-workouts-mcp).

**Por qué**:
- La API Policy de Strava (sección 5.3, 2026) prohíbe usar sus datos para
  operar aplicaciones de IA, incluido pasarlos al contexto de un modelo; la
  única excepción es su MCP oficial, pensado para asistentes conversacionales
  y no para un backend desatendido. Eso descarta el nodo Strava de n8n y los
  MCP comunitarios de Strava.
- Entre los servidores MCP de Garmin revisados (Nicolasvegam, garth-mcp-server,
  bmccarn, st3v, ...), Taxuspt es el único que lee **y** programa
  entrenamientos en un solo servidor, con Docker y transporte HTTP, y es el
  más usado (≈1,3k estrellas), lo que importa cuando Garmin cambie su login.
- Que tenga 110+ tools no cuesta tokens: el LLM no las recibe.

**Riesgos aceptados**: usa `python-garminconnect`, API no oficial de Garmin
(puede romperse si Garmin cambia su login); el contenedor guarda tokens con
acceso total a la cuenta, por lo que nunca se publica a internet (solo red
interna de Docker, sin puerto expuesto); los tokens caducan (~6 meses) y
re-autenticar con MFA es manual — n8n debe avisar cuando falle el login.

## 2026-10-06 — Despliegue en VPS de Hostinger

**Decisión**: el `docker-compose` (`n8n`, `pb-coach`, `garmin-mcp`) corre en
el VPS de Hostinger del usuario, donde vive n8n.

**Por qué**: el VPS ya existe y ya aloja n8n; un solo host con red interna
de Docker evita exponer `pb-coach` y `garmin-mcp`.

## 2026-10-06 — Metodologías: Uphill Athlete y Nacho Martínez

**Decisión**: se transcribirán dos perfiles: "Training for the Uphill
Athlete" (House & Johnston) y "Trail Running: ciencia y entrenamiento"
(Nacho Martínez). Se mantiene un perfil activo por plan; cuál se usa en
cada modo (construcción / competición) se decide al transcribirlos.

**Por qué**: Uphill Athlete encaja con el modo construcción (base aeróbica y
fuerza para montaña); Nacho Martínez aporta una referencia de trail
específica en español, útil sobre todo para el modo competición.

## 2026-10-06 — n8n dedicado en el compose, sin exposición pública

**Decisión**: el `docker-compose` del proyecto incluye su propio n8n
(`n8nio/n8n`, versión fijada). Solo n8n publica un puerto, y únicamente en
`127.0.0.1` del VPS; al editor se entra con un túnel SSH
(`ssh -L 5678:localhost:5678 usuario@vps`). `pb-coach` y `garmin-mcp` no
publican puertos: n8n llama a `pb-coach` por la red interna de Docker. Zona
horaria del stack: `America/Guayaquil`.

**Por qué**: un n8n propio deja el proyecto autocontenido (un solo
`docker compose up`, workflows versionables en el repo) y aislado del n8n de
automatizaciones personales. Nada de lo que hace este n8n (cron, llamar a
pb-coach, enviar a Telegram) necesita conexiones entrantes, así que el stack
queda sin superficie pública — importante porque garmin-mcp tiene acceso a la
cuenta de Garmin. Si en el futuro se quiere exponer (p. ej. un bot de
Telegram con trigger entrante), se hará en una nueva versión que se conecte
al n8n online existente.

## 2026-10-06 — uv para entornos y dependencias; imagen Docker con uv

**Decisión**: dependencias declaradas en `pyproject.toml` (grupo `dev` vía
`[dependency-groups]`), versiones exactas en `uv.lock`, Python 3.12 fijado
en `.python-version`. El `Dockerfile` copia `uv` desde su imagen oficial
(versión fijada) e instala con `uv sync --locked`; targets `runtime`
(usuario no root, healthcheck) y `test`.

**Por qué**: un solo lockfile reproducible tanto en local como en el
contenedor, instalación rápida y cacheable por capas, y menos piezas que
mantener que pip + venv + requirements.

## 2026-10-06 — Carga: EPOC de Garmin, sRPE como respaldo; objetivos en tiempo

**Decisión**: la carga de una sesión es la carga de entrenamiento de Garmin
(basada en EPOC, campo `carga_epoc` de `SesionRealizada`); como respaldo,
sRPE = RPE x minutos. Las dos se calculan como series paralelas y **nunca se
suman entre sí**: al comparar dos periodos, `comparar_carga` usa EPOC si
todas las sesiones de ambos periodos lo tienen, si no sRPE con la misma
condición, y si ninguna está completa devuelve None en vez de un número
parcial. Además, `ObjetivosMicrociclo` acepta el volumen semanal en tiempo
(`duracion`), en km o en ambos.

**Por qué**: EPOC no requiere esfuerzo del atleta y lo calcula el reloj; sRPE
es el estándar de la literatura cuando falta. Están en escalas distintas
(~120 vs ~420 para la misma sesión), así que mezclarlas falsearía cualquier
porcentaje de progresión. Los objetivos en tiempo reflejan cómo se planifica
en trail y en Uphill Athlete, donde los km con desnivel no son comparables.

## 2026-10-06 — Progresión: la descarga no es referencia

**Decisión**: en las reglas de incremento máximo de volumen, cada semana de
carga se compara con la **última semana de carga**, nunca con una de
descarga. Tras una descarga se vuelve al nivel previo y se sigue
progresando con el mismo límite (40 → 44 → descarga 30 → 48 es válido;
→ 55 es un salto del +25% y es violación).

**Por qué**: así es como se trabaja la descarga (bajar, volver al nivel
anterior y seguir subiendo de forma progresiva). Comparar contra la
descarga marcaría como violación cada vuelta normal y, a la vez, abriría la
puerta a saltos grandes justo después de descargar.

## 2026-10-06 — Cierre de semana: clasificación y prioridad de acciones

**Decisión**: `deviation.evaluar_semana` clasifica las sesiones realizadas
(heredando clase y tipo de la sesión planificada del mismo día, o, si no
hay, solo la clase por zona de FC: Z2 → Fondo, Z3–Z5 → Específico; Z1 queda
sin clasificar por ambigua), mide adherencia de volumen y de sesiones y RPE
medio, y evalúa las `reglas_ajuste`. Si se activan varias, gana la acción
más conservadora: reducir_carga > adelantar_descarga > repetir_microciclo >
extender_mesociclo > mantener > progresar; se informan todas las activadas.
Si ninguna se activa, no hay acción y se sigue el plan. Una regla cuya
métrica no está disponible (p. ej. un test que aún no se hizo) queda como no
evaluable. Las métricas de progreso entran como `metricas_externas`.

**Por qué**: ante señales de fatiga, proteger al atleta va antes que
progresar. Deducir el tipo de sesión (Tempo, Umbral o Series) solo por la
zona sería adivinar, así que `SesionRealizada` admite clase sin tipo.

## 2026-10-06 — Postgres para pb-coach y n8n (reemplaza a SQLite)

**Decisión**: un servicio `postgres` (18.6) en el compose, sin puertos
publicados, con dos bases separadas — `n8n` y `pb_coach` —, cada una con su
usuario y sin permiso de conexión a la otra (`docker/postgres/init.sql`).
n8n deja su SQLite interno y usa su base; pb-coach usará la suya vía
SQLAlchemy + Alembic, guardando las versiones del plan como JSONB. El
contenedor pb-coach recibe solo sus variables, nunca la contraseña del
superusuario.

**Por qué**: con Docker Compose ya en marcha, la ventaja de SQLite (no
levantar un servidor) pesa poco, y Postgres da: una sola base robusta para
n8n y pb-coach con un único punto de backup (`pg_dump`), JSONB para
consultar dentro de los planes versionados (qué cambió entre versiones,
qué acciones de ajuste se aplicaron) y el flujo estándar de un proyecto
real (ORM + migraciones). Coste: un contenedor más (~50–100 MB) y tests de
persistencia contra un Postgres levantado; el motor sigue siendo puro y sus
tests no cambian.

## 2026-10-06 — Diseño de la persistencia

**Decisión**: tablas `plan` (un ciclo; uno solo activo), `plan_version`
(cada versión completa como JSONB, inmutable, con el motivo del cambio),
`sesion_realizada` (columnas normales, `garmin_activity_id` único para que
el sync sea idempotente) y `ejecucion_agente` (resultado y tokens). El
esquema lo gestiona Alembic con migraciones escritas a mano; pb-coach las
aplica al arrancar. El repositorio no hace commit (lo decide quien llama,
para que un ajuste semanal sea todo o nada) y vuelve a validar con Pydantic
cada plan que lee. Los tests de persistencia corren contra Postgres real en
un esquema temporal y verifican que la migración coincide con los modelos.

**Por qué**: versiones inmutables dan el historial completo de qué cambió y
por qué regla; validar al leer impide que un dato inconsistente en la base
llegue al motor como válido; probar contra el Postgres real evita las
diferencias de comportamiento que tendría una base de pruebas distinta.

## 2026-10-06 — Sync de Garmin: mapeo, zonas y clasificación

**Decisión**:
- `mcp_client/garmin.py` traduce actividades de running (`running`,
  `trail_running`, `track_running`, `treadmill_running`) a `SesionRealizada`
  con una lista blanca de tools (`get_activities_by_date`, `get_activity`,
  `get_activity_hr_in_timezones`). Carga EPOC = `training_load`; RPE =
  `workout_rpe` / 10; sensaciones = `workout_feel`.
- El RPE y las sensaciones anteriores al 2026-10-07 se ignoran
  (`GARMIN_RPE_DESDE`): antes no se registraban con criterio.
- En trail el terreno queda vacío (Garmin no distingue camino, sendero o alta
  montaña): cuenta el desnivel. `running` → Asfalto, `track_running` → Pista.
- `SesionRealizada` guarda los segundos reales en cada zona de FC
  (`segundos_por_zona`) en vez de una sola zona, y **las sesiones ya no se
  clasifican por zona**: solo heredan la clase de la sesión planificada del
  mismo día; sin pareja quedan sin clasificar.
- `pb_coach.sync` trae desde la última fecha guardada (la primera vez, 56
  días de línea base) y guarda sin duplicar.

**Por qué**: en montaña el pulso sube en las subidas aunque el esfuerzo sea
de fondo, y en este atleta incluso la base cae en Z3–Z4 (en sus datos reales,
50–68% del tiempo semanal en Z4). Clasificar por zona confundiría Fondo con
Específico; resumir en una zona falsearía la intensidad. Las zonas de Garmin
por defecto probablemente no reflejan su umbral aeróbico real: conviene
fijarlas con el test que proponga la metodología (pendiente al transcribir
el perfil).

## 2026-10-06 — Agente: bucle manual, contexto en memoria y guardia en la entrega

**Decisión**:
- Bucle manual de tool use con `claude-opus-5-5` (effort `high`, tools con
  `strict: true`, `fallbacks: "default"`, system cacheado), en vez del Tool
  Runner del SDK, para controlar iteraciones, revisión de cada entrega,
  rechazos y respuestas truncadas, y poder probarlo con un cliente falso.
- El agente trabaja sobre un contexto cargado antes del bucle (perfil,
  sesiones, plan vigente y la evaluación de la semana cerrada ya calculada
  por el motor); no toca la base de datos. El servicio persiste versión y
  ejecución en una sola transacción, solo si el resultado fue aceptado.
- Tools: obtener_perfil, resumen_historial (solo semanas cerradas),
  obtener_plan, evaluar_semana, validar_plan y entregar_resultado. Los planes
  viajan como JSON en texto y se validan con Pydantic en el servidor, para
  devolver al modelo el error exacto.
- La guardia corre dentro de entregar_resultado: re-valida el plan, rechaza
  regla_ids inexistentes, exige la acción decidida por el motor, que las
  semanas pasadas no cambien, la versión siguiente y la próxima semana
  detallada. Si rechaza, el modelo corrige y vuelve a entregar.
- La API exige un token compartido; sin token configurado no opera.

**Por qué**: la garantía "nunca inventa metodología" vive en código que se
puede testear, no en el prompt. Separar contexto, bucle y persistencia hace
cada parte comprobable sin red ni coste.

**Límite conocido**: la guardia comprueba que se cite la acción de ajuste,
no que el plan la aplique correctamente (p. ej. que "repetir_microciclo"
realmente repita la semana). Verificarlo requiere reglas por acción en el
motor; queda pendiente.
