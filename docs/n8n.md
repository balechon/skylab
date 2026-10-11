# Integración con n8n

n8n es el orquestador: dispara el proceso (cron semanal o ejecución manual),
llama a los servicios de PB_coach por la red interna de Docker y envía el
resultado (p. ej. por Telegram). No contiene lógica de dominio.

Todas las llamadas (salvo `/health`) llevan la cabecera
`Authorization: Bearer <PB_COACH_API_TOKEN>`.

## Servicios

| Servicio | URL interna | Endpoints |
|---|---|---|
| pb-coach-sync | `http://pb-coach-sync:8000` | `POST /sync` → `{ok, resultado: {desde, hasta, traidas, nuevas}}`; 502 con `{ok: false, error}` si Garmin falla |
| pb-coach-api | `http://pb-coach-api:8000` | `POST /plan`, `POST /semana/ajustar` → `{estado, resumen, plan_id, version, accion, justificaciones, violaciones, detalle, tokens_entrada, tokens_salida}` |

## Workflow semanal (cron, domingo)

1. `POST pb-coach-sync /sync`. Si responde 502, seguir igualmente (la API
   planifica con los datos ya guardados) y anotar el error para el aviso.
2. `POST pb-coach-api /semana/ajustar`. 409 si no hay plan activo.
3. Enviar `resumen`, `accion` y `justificaciones` por Telegram.

## Workflow manual (nuevo ciclo)

1. `POST pb-coach-sync /sync`.
2. `POST pb-coach-api /plan` con
   `{"modo": "Construcción", "perfil": "<perfil>", "fecha_objetivo": "AAAA-MM-DD"}`
   (y `"carrera"` en modo Competición).
