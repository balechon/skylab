# API de PB_coach

Dos servicios HTTP, publicados solo en `127.0.0.1` del host. En el VPS se
llaman a través de un túnel SSH:

```bash
ssh -L 8000:localhost:8000 -L 8001:localhost:8001 usuario@vps
```

Todas las llamadas (salvo `GET /health`) llevan la cabecera
`Authorization: Bearer <PB_COACH_API_TOKEN>`. Sin token configurado, los
servicios responden 503.

## Servicios

| Servicio | Puerto | Endpoints |
|---|---|---|
| pb-coach-api | 8000 | `POST /plan`, `POST /semana/ajustar` |
| pb-coach-sync | 8001 | `POST /sync`, `POST /publicar` |

**pb-coach-api**
- `POST /plan` con `{"modo": "Construcción", "perfil": "<perfil>", "fecha_objetivo": "AAAA-MM-DD"}`
  (y `"carrera"` en modo Competición) → crea un ciclo nuevo. 404 si el perfil
  no existe; 422 si el perfil no define la secuencia de bloques del modo.
- `POST /semana/ajustar` → evalúa la semana cerrada y crea la versión
  siguiente del plan vigente. 409 si no hay plan activo.
- Ambos responden `{estado, resumen, plan_id, version, accion,
  justificaciones, violaciones, detalle, tokens_entrada, tokens_salida}`.

**pb-coach-sync**
- `POST /sync` → actividades de Garmin a Postgres:
  `{ok, resultado: {desde, hasta, traidas, nuevas}}`.
- `POST /publicar` → la próxima semana del plan vigente al calendario de
  Garmin (y al reloj): `{ok, resultado: {plan_id, version, semana, publicados,
  retirados, sin_cambios, avisos}}`. 409 si no hay plan o la semana no está
  detallada.
- 502 con `{ok: false, error}` si Garmin falla. La API sigue funcionando con
  los datos ya guardados.

## Ciclo semanal

Por ahora se lanza a mano; cómo programarlo está pendiente de decidir.

```bash
TOKEN=$(grep ^PB_COACH_API_TOKEN= .env | cut -d= -f2)
H="Authorization: Bearer $TOKEN"

curl -X POST -H "$H" localhost:8001/sync              # 1. Garmin → Postgres
curl -X POST -H "$H" localhost:8000/semana/ajustar    # 2. versión nueva del plan
curl -X POST -H "$H" localhost:8001/publicar          # 3. próxima semana → reloj
```

## Nuevo ciclo

```bash
curl -X POST -H "$H" localhost:8001/sync
curl -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"modo": "Construcción", "perfil": "<perfil>", "fecha_objetivo": "2026-12-31"}' \
  localhost:8000/plan
curl -X POST -H "$H" localhost:8001/publicar
```

## Nota para Windows (Git Bash)

`curl -d '{"modo": "Construcción", ...}'` puede enviar la "ó" en una
codificación que no es UTF-8 y la API responde `400 There was an error
parsing the body`. Guarda el JSON en un archivo UTF-8 y envíalo con
`--data-binary`:

```bash
curl -X POST -H "$H" -H "Content-Type: application/json; charset=utf-8" \
  --data-binary @solicitud.json localhost:8000/plan
```

En Linux (el VPS) no pasa.
