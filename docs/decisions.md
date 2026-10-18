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

> **Reemplazada (2026-10-17)**: n8n se quitó del proyecto. Ver "Fuera n8n" más abajo.

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

> **Reemplazada (2026-10-17)**: n8n se quitó del proyecto. Ver "Fuera n8n" más abajo.

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

## 2026-10-11 — Workspace de uv y una imagen por servicio; MCP aislado

**Decisión**: el código pasa a un workspace de uv con cuatro paquetes, cada
uno con su `pyproject.toml` y solo sus dependencias: `pb-coach-core`
(domain + engine: pydantic, pyyaml), `pb-coach-persistence` (sqlalchemy,
alembic, psycopg), `pb-coach-sync` (mcp) y `pb-coach-api` (anthropic,
fastapi). `pb_coach` es un namespace package compartido, así que los imports
no cambian. Hay dos imágenes de runtime por proceso: `pb-coach-api` (API +
agente, sin MCP) y `pb-coach-sync` (sync de Garmin, sin FastAPI ni la clave de
Anthropic), más una de tests con todo. La API ya no sincroniza: n8n llama
primero a `pb-coach-sync /sync` y después a `pb-coach-api`.

**Por qué**: el SDK de MCP es la dependencia más pesada y comparte base
(starlette) con FastAPI; separarlas evita que un conflicto de versiones o un
fallo de Garmin tumbe la planificación, y aísla los errores de cada parte.
Separar paquetes además hace cumplir los límites entre capas (core no puede
importar SQLAlchemy porque no lo tiene). No se hizo una imagen por directorio:
domain y engine son librerías que usan todos, y partir el agente del motor
obligaría a cada validación a pasar por HTTP.

**Nota**: el workspace comparte un único `uv.lock` (las versiones se
resuelven juntas); lo que cambia es qué se instala en cada imagen
(`uv sync --package`).

## 2026-10-11 — Estructura plana: cada carpeta es un paquete

**Decisión**: se quitan los niveles `packages/` y `src/pb_coach/`. Cada
paquete del workspace es una carpeta en la raíz con su `pyproject.toml` y sus
scripts directamente dentro, y se importa por su nombre: `core` (antes
domain + engine, aplanados), `persistence`, `sync` (cliente MCP de Garmin +
servicio de sync) y `agent` (agente + `api.py`; paquete `pb-coach-agent`).
Las imágenes copian solo sus carpetas e instalan el código no editable en
`/src/.venv`, corriendo desde `/app`: en la imagen de la API no se puede
importar `sync`, ni `agent` en la del sync.

**Por qué**: menos niveles de carpetas y nombres más directos, sin perder la
separación de dependencias ni de imágenes de la decisión anterior.

## 2026-10-17 — Secuencia de bloques en el perfil

**Decisión**: el perfil define `secuencias_bloques`: por cada modo
(construcción / competición), qué mesociclos tocan y en qué orden. El
validador exige que los mesociclos del plan sigan esa secuencia (puede usar
solo los primeros bloques si el horizonte es corto, pero no saltar,
reordenar ni añadir). La guardia exige además citar el ID de la secuencia.
Si el perfil no tiene secuencia para el modo pedido, el servicio rechaza la
petición antes de llamar al modelo (HTTP 422). Se prevé, más adelante,
permitir que la solicitud fije los bloques a mano como excepción.

**Por qué**: en la primera prueba real el modelo eligió por su cuenta los
bloques futuros (Potencia aeróbica, Umbral), contradiciendo el plan de base y
fuerza hasta fin de año; lo avisó, pero la guardia no podía detectarlo
porque nada lo regulaba. Con la secuencia en el perfil, el objetivo de cada
bloque lo decide la metodología. En la segunda prueba real el plan siguió
la secuencia (Base aeróbica → Fuerza y economía) y la citó.

## 2026-10-17 — Publicar la semana en el reloj vía garmin-mcp

**Decisión**: se mantiene `garmin-mcp` (opción A) también para escribir. Cada
`SesionPlanificada` se traduce en código determinista (`sync/entrenamientos.py`)
al JSON de entrenamiento de Garmin y se sube con `upload_workout`, en vez de
usar las tools simplificadas, porque estas no aceptan notas. Pasos por tiempo
(o distancia si la sesión solo tiene distancia) con objetivo de zona de FC;
lo que el reloj no estructura (desnivel, terreno, indicaciones) va en las
notas (`description`). `SesionPlanificada` gana `calentamiento`, `intervalos`
(repeticiones × trabajo + recuperación) y `vuelta_calma`; las Series exigen
`intervalos` y, con series, la estructura debe sumar la duración.
`POST /publicar` (servicio sync) publica la próxima semana del plan vigente:
retira (quita del calendario y borra) lo publicado de otra versión para esas
fechas, sube y programa lo nuevo, y lo registra en `publicacion_garmin`.
Volver a publicar la misma versión no hace nada; lo borrado a mano en Garmin
genera un aviso, no un fallo. Publicar es un paso fijo, nunca una tool del LLM.

**Por qué**: garmin-mcp ya expone la escritura y planificamos por tiempo y
FC (en trail el ritmo y los km engañan), que es lo que mejor cubre. Las
notas llevan al reloj el detalle de trail que no tiene campos propios.

**Lección**: los planes guardados como JSONB se revalidan al leerse; al
endurecer el modelo (aquí, Series con estructura obligatoria) los planes de
prueba anteriores dejaron de ser válidos. Cambios así necesitarán migrar los
planes guardados.

## 2026-10-17 — Fuera n8n; API y Garmin publicados en 127.0.0.1

**Decisión**: se quita n8n del proyecto (servicio, volumen, su base en
Postgres para instalaciones nuevas y sus variables). La API (8000) y el
servicio de Garmin (8001) se publican solo en `127.0.0.1` del host; en el VPS
se llaman por túnel SSH, siempre con `PB_COACH_API_TOKEN`. El ciclo semanal
(sync → ajuste → publicar) se lanza a mano con tres llamadas (ver
`docs/api.md`); cómo programarlo queda pendiente de decidir.

**Por qué**: n8n añadía dos piezas (su contenedor y su base) para hacer solo
de cron y de aviso; la parte valiosa del proyecto —planificar y publicar en
el reloj— vive en el código. Sin n8n el stack es más simple y la
programación se decidirá aparte (p. ej. dentro de la API o con el cron del
VPS).

## 2026-10-17 — El agente pasa a LangGraph, independiente del proveedor

**Decisión**: el bucle manual sobre el SDK de Anthropic se reemplaza por un
grafo de LangGraph (`agent/agente.py`: nodos modelo, herramientas y
recordatorio) y el modelo llega como `BaseChatModel` de LangChain. El modelo
se elige con `PB_COACH_MODELO` ("proveedor:modelo", por defecto
`anthropic:claude-opus-5-5`); lo específico de cada proveedor vive solo en
`agent/modelo.py` (en Anthropic: `effort` alto, `fallbacks: "default"` y caché
del system). Las tools se definen en formato neutro y se enlazan con
`strict=True`. No cambian las tools, la guardia, el contexto, el servicio, la
API ni la persistencia; el contrato sigue siendo `ejecutar_agente(ctx, modelo)
→ EjecucionAgente`. Los tests usan un `BaseChatModel` falso.

**Por qué**: LangGraph es un estándar de la industria y permite cambiar de
modelo o proveedor sin tocar el agente. Además deja la puerta abierta a
pausas con checkpoints en Postgres (p. ej. aprobar el plan antes de
publicarlo en el reloj). Se acepta que es algo de sobreingeniería para el
flujo actual, lineal, y el coste: la imagen de la API pasa de 388 MB a
462 MB. Con otro proveedor, las opciones exclusivas de Anthropic se pierden.

## 2026-10-17 — Estructura estándar del módulo agent

**Decisión**: `agent/` queda con un archivo por razón de cambio, como en la
mayoría de proyectos con LangGraph: `api.py` (HTTP), `servicio.py` (cargar
contexto → grafo → guardar), `grafo.py` (antes agente.py), `herramientas.py`,
`guardia.py`, `prompts.py`, `llm.py` (antes modelo.py: proveedor y opciones)
y `esquemas.py` (contratos de entrada y salida; antes contexto.py y
resultado.py). Los prompts se mantienen separados de `llm.py`.

**Por qué**: los prompts cambian al ajustar el comportamiento y deben valer
para cualquier proveedor; `llm.py` cambia al cambiar de proveedor. "Modelo"
también significa modelo de datos en este proyecto, de ahí `llm.py`. Regla
general: lo que funcionaría igual sin un LLM no va en `agent/`.

## 2026-10-17 — Bloque en curso completo y ajuste semanal idempotente

**Decisión**:
- La guardia exige que el mesociclo en curso tenga todas sus semanas
  definidas (nivel 2 como mínimo), sin huecos, de su primer a su último día.
  Al entrar en un bloque nuevo, el agente está obligado a pasarlo de
  esqueleto a semanas con objetivos; los bloques futuros pueden seguir siendo
  esqueleto.
- Cada ajuste semanal registra la semana cerrada que evaluó
  (`ejecucion_agente.semana`, migración 0004). Si esa semana ya tiene un
  ajuste aceptado, `POST /semana/ajustar` responde 409 sin llamar al modelo;
  `?forzar=true` lo rehace. Un ajuste fallido no cuenta como hecho.

**Por qué**: antes, el paso de un bloque al siguiente dependía solo del
prompt. Y cuando el ciclo semanal se programe, lanzarlo dos veces (un
reintento, un cron duplicado) no debe generar dos versiones ni gastar
tokens. Sigue pendiente: si un domingo no se ejecuta, la semana anterior no
se evalúa (solo se evalúa la última cerrada).

## 2026-10-17 — El LLM aporta lenguaje: comentarios del atleta y feedback semanal

**Decisión**: el ajuste semanal acepta comentarios del atleta (uno general,
para lo que viene, y uno por sesión) y el agente recibe la semana cerrada
día a día —planificado, realizado, RPE y sensación de Garmin, y comentario—,
calculada por el motor (`core/deviation.comparar_dias`). `ResultadoAgente`
gana un `feedback` para el atleta (qué pasó, por qué cambia el plan y hasta
3 consejos). La guardia lo exige en el ajuste semanal, exige que "por qué
cambia" cite la regla de la acción del motor y que los consejos que se
apoyan en la metodología citen reglas existentes. Ante dolor o lesión, el
agente no da consejo médico: baja la carga dentro de las reglas y recomienda
consultar a un profesional. Los comentarios quedan registrados con la
ejecución.

**Por qué**: con el motor y la guardia, componer un plan válido podría
hacerlo un programa sin LLM. El valor del modelo está en el lenguaje: leer lo
que el atleta cuenta (cómo se sintió, viajes, molestias) junto a sus datos y
explicarle la semana de forma personalizada. Es la base de la interfaz en
Notion (fase B).

## 2026-10-17 — Carreras con prioridad A/B/C y datos del atleta fuera del YAML

**Decisión**: la metodología sigue en YAML (git); los datos del atleta (ficha,
carreras, tests, semanas, entrenamientos) vivirán en Notion y llegarán a la
API a través de un servicio aparte. Las carreras tienen prioridad A
(objetivo), B (competir) o C (participar) y cuentan en los dos modos; una C
es una sesión más de la semana. El tratamiento de cada prioridad sale de
`reglas_carreras` en el perfil. Detalle en `docs/entradas.md`.

**Por qué**: priorizar carreras es como trabajan los entrenadores y permite un
plan personalizado (una C por diversión no rompe la progresión hacia la A)
sin que el LLM invente cómo tratar cada una.

## 2026-10-17 — Ficha del atleta con disponibilidad como restricción dura

**Decisión**: `core/athlete.py` define la ficha (edad, categoría, umbrales de
FC, disponibilidad, lesiones). Se guarda versionada en Postgres
(`ficha_atleta`, migración 0005), entra por `PUT /atleta` (después la enviará
el servicio de Notion) y cada ejecución guarda una copia. La guardia rechaza
sesiones en días libres, días que superan el máximo y más días largos por
semana de los permitidos; con disponibilidad definida, toda sesión necesita
`duracion_objetivo`. La disponibilidad manda sobre la metodología: si el
perfil pide más de lo que cabe, el agente adapta y lo explica.

**Por qué**: la metodología (Uphill Athlete) pide 5 o más sesiones y salidas
largas que pueden no caber en la semana real del atleta. Sin una restricción
dura en código, el plan sería bonito pero imposible de cumplir.

## 2026-10-17 — Zonas de FC por umbrales, calculadas en código

**Decisión**: el perfil define las zonas relativas a los umbrales del atleta
(`zonas_fc`: p. ej. Z1 de AeT − 20 % a AeT − 10 %). El servicio calcula las
pulsaciones con la ficha (`core/athlete.rangos_fc`) y las guarda en
`Plan.rangos_fc` al aceptar el plan, descartando lo que haya puesto el LLM.
La publicación envía cada paso al reloj como rango a medida
(`targetValueOne/Two`) y añade "FC 119-134" a las notas. Si falta un umbral
(sin LT no hay Z3 ni Z4), esa zona va con la zona genérica de Garmin.

**Por qué**: Uphill Athlete basa todo en el umbral aeróbico propio y las
zonas de Garmin (por FC máxima) no lo reflejan: con ellas casi todos los
rodajes del atleta caían en Z3. Las cifras salen del perfil y de la ficha,
nunca del modelo.

## 2026-10-17 — Tipos de semana y reglas según el atleta

**Decisión**: `TipoMicrociclo` añade Base, Intensidad, Especificidad, Taper
y Carrera (la R del libro es Descarga); `es_carga` decide qué semanas cuentan
para la progresión. El perfil puede fijar sus `tipos_semana` (con la receta
de cada uno) y el plan solo puede usar esos. Las reglas pueden limitarse a
ciertos tipos de semana (`tipos_microciclo`) y a ciertos atletas (`solo_si`:
con o sin deficiencia aeróbica, según el test del 10 % con los umbrales de la
ficha). Si no se puede saber si una regla aplica, queda como no evaluable,
nunca como cumplida. Evaluadores nuevos: reducción de la descarga, proporción
mínima de la salida larga y máximo de tiempo en Z2.

**Por qué**: Uphill Athlete organiza el macrociclo por tipos de semana y
cambia sus reglas según el atleta (p. ej. una o dos sesiones intensas según
la deficiencia aeróbica). Sin esto, esas reglas quedaban solo en el prompt.

## 2026-10-18 — Perfil de Uphill Athlete activo, con guía del autor

**Decisión**: el perfil pasa a `methodology/profiles/uphill_athlete.yaml`.
Lo que el motor no comprueba (semanas y macrociclos de ejemplo, tests,
categorías, reglas por prioridad de carrera, notas A–F) va en un bloque
`guia` que el agente lee y puede citar por id. `PerfilMetodologia` prohíbe
claves desconocidas: antes, el loader descartaba en silencio cualquier
sección que el modelo no conociera.

Umbrales del atleta tras el test del 2026-10-18: AeT 164 (ventilatorio), LT
179 (estimación de Garmin; el test dio 170 con subida incompleta), sin
deficiencia aeróbica. Zonas de running configuradas en Garmin Connect con
los mismos límites que el perfil, para que el tiempo por zona sincronizado
use las zonas del plan.

## 2026-10-18 — El tiempo por zona no mezcla zonas distintas

**Decisión**: cada sesión guarda los suelos de zona con los que Garmin calculó
su tiempo por zona (`limites_zonas`, migración 0006). Con las zonas del atleta
(perfil + ficha), el resumen del historial y la evaluación semanal solo suman
el tiempo de las sesiones registradas con esas mismas zonas; las demás se
cuentan como no comparables y se clasifican, aproximadamente, por su FC media.
`python -m sync rellenar-zonas <desde>` completa las sesiones ya guardadas.

**Por qué**: Garmin no recalcula las actividades pasadas al cambiar las
zonas. En la primera creación del plan, el agente leyó el historial con las
zonas antiguas (por FC máxima) y concluyó que el atleta entrenaba casi todo en
Z3–Z4, cuando con su umbral aeróbico eran rodajes en Z2.
