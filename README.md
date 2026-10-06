# PB_coach

Coach personal de running/trail basado en un agente de IA. Planifica ciclos
completos de entrenamiento según una metodología explícita, evalúa cada
semana lo que realmente entrené (adherencia y progreso) y ajusta lo que
viene, justificando cada decisión con el ID de la regla que la produjo.

Tiene dos modos: **construcción** (progresar sin carrera de referencia) y
**competición** (llegar en forma a una carrera). Nunca inventa metodología:
la aplica. Si no puede cumplir las restricciones, lo dice en vez de producir
un plan bonito e incoherente.

Visión completa: [`docs/vision.md`](docs/vision.md). Decisiones:
[`docs/decisions.md`](docs/decisions.md).

Este proyecto es también un ejercicio de aprendizaje de agentes de IA,
n8n y MCP.

## Principio de diseño

El sistema es un motor híbrido:

- **Motor determinista (Python)**: calcula carga/volumen/intensidad,
  valida restricciones de la metodología activa, detecta desviación entre
  plan y realidad. Es la única autoridad sobre "¿esto cumple la
  metodología?". Se testea con unit tests.
- **Agente LLM**: interpreta el objetivo del usuario, propone la
  composición de la rutina y los ajustes, evalúa el progreso en lenguaje
  natural y redacta la justificación citando el ID de regla exacto que el
  motor determinista usó. Nunca decide por sí solo si algo es válido —
  propone dentro del espacio que el motor aprueba o rechaza.

## Flujo

```
n8n ── cron semanal ──▶ POST /semana/ajustar ─┐
    └─ manual ────────▶ POST /plan ───────────┤
                                              ▼
                        pb-coach (Docker): API mínima
                          ├─ sync / publicar ◀──▶ garmin-mcp ◀──▶ Garmin
                          ├─ agente LLM (propone)
                          ├─ motor determinista (decide)
                          ├─ perfiles YAML (metodología)
                          └─ PostgreSQL (planes versionados, sesiones)
n8n ◀── resultado ── Telegram
```

![Arquitectura](docs/arquitectura.png)

## Estructura del proyecto

```
methodology/    Perfiles de metodología (YAML), uno por autor/framework
src/pb_coach/
  domain/       Modelos de datos puros (Sesión, Mesociclo, Plan, ...)
  engine/       Motor determinista: loader, calculator, validator, deviation
  agent/        Capa LLM: bucle (agente), tools, guardia final y servicio
  mcp_client/   Cliente MCP de garmin-mcp (sync de actividades, publicar semana)
  persistence/  Postgres: modelos SQLAlchemy y repositorio
  api/          API HTTP mínima (FastAPI)
  integrations/n8n/  Contrato de los webhooks que n8n dispara
migrations/     Migraciones de Alembic (se aplican al arrancar pb-coach)
tests/          Tests, principalmente del motor determinista
docs/           Visión, decisiones y diagramas (fuente HTML en docs/*/)
```

## Estado actual

- Hecho: modelos de dominio alineados con la visión (modos construcción /
  competición, tres niveles de detalle, sesión planificada vs. realizada,
  reglas de ajuste), loader de perfiles, perfil didáctico, API con `/health`
  y stack Docker (n8n + pb-coach + garmin-mcp), todo con tests.
- Hecho también: motor determinista completo (`engine/calculator.py`,
  `validator.py`, `deviation.py`) y Postgres en el stack (n8n ya lo usa).
- Hecho también: persistencia en Postgres (`persistence/`, SQLAlchemy +
  migraciones Alembic en `migrations/`).
- Hecho también: sync de Garmin (`pb_coach.sync`) y agente LLM (`agent/`:
  bucle de tool use con Claude, guardia final y servicio que persiste),
  expuesto en la API (`POST /plan`, `POST /semana/ajustar`, `POST /sync`).
- Siguiente: publicar la semana en el reloj, workflows de n8n y transcribir
  el primer perfil real.

## Setup

Entorno y dependencias con [uv](https://docs.astral.sh/uv/) (Python 3.12,
fijado en `.python-version`; versiones exactas en `uv.lock`):

```bash
uv sync            # crea .venv e instala dependencias + grupo dev
uv run pytest      # tests (los de Postgres se saltan sin TEST_DATABASE_URL)
uv add <paquete>   # nueva dependencia (actualiza pyproject.toml y uv.lock)
```

## Docker

```bash
docker compose up -d --build                    # pb-coach en 127.0.0.1:8000 (/health)
docker compose run --rm --build test            # todos los tests, incluidos los de Postgres
docker compose --profile garmin up -d --build   # + garmin-mcp
```

`garmin-mcp` necesita tus credenciales de Garmin en `secrets/` (ignorado por
git) y un primer login interactivo para el código MFA:

```bash
mkdir -p secrets
printf '%s' 'tu_email' > secrets/garmin_email.txt
printf '%s' 'tu_password' > secrets/garmin_password.txt
docker compose --profile garmin run --rm garmin-mcp
```
