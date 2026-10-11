# Visión de PB_coach

Definida el 2026-10-06. Este documento fija **qué** construimos y **por qué**;
el **cómo** de cada decisión vive en `docs/decisions.md`.

## En una frase

Un agente de IA que me hace progresar de forma continua como corredor de
trail, usando la velocidad como herramienta, planificando ciclos completos
según una metodología explícita y ajustándolos cada semana según lo que
realmente entrené.

## Para quién

Para un solo usuario: yo. No hay página web, cuentas de usuario ni
despliegue complejo. El sistema corre en un host propio y me llega el
resultado por notificación.

## Qué lo diferencia de un plan de Garmin

Las herramientas existentes ya se adaptan solas; adaptarse no es el
diferencial. Lo es:

1. **Modo construcción** — progresar sin una carrera de referencia,
   subiendo el techo de forma progresiva. La mayoría de herramientas solo
   planifican hacia atrás desde una carrera.
2. **Híbrido trail + velocidad** — corredor de montaña que usa sesiones de
   velocidad (asfalto/pista) para rendir mejor en trail. `terreno` es un
   dato de cada sesión, no del plan.
3. **Transparencia** — mi metodología, explícita en YAML; cada decisión del
   plan cita el ID de la regla que la produjo. Si no se pueden cumplir las
   reglas, el sistema lo dice en vez de inventar.

## Dos modos de plan

| | Construcción | Competición |
|---|---|---|
| Horizonte | Hacia adelante, bloque a bloque | Hacia atrás desde la fecha de la carrera |
| Fin | Fecha de corte | Día de la carrera |
| Mesociclos típicos | Base aeróbica, Fuerza y economía | Específico competencia, Puesta a punto |
| Éxito | Mejoran los indicadores de progreso | Llegar en forma ese día |

**Plan inicial**: modo construcción desde octubre hasta el 31 de diciembre
de 2026, con foco en base y fuerza. En 2027, modo competición en base a las
carreras elegidas. La transición entre modos se rige por reglas del perfil.

## Planificación rodante

1. **Crear ciclo** (una vez por objetivo, manual): genera el plan completo.
2. **Ajuste semanal** (automático): cierra la semana pasada, la evalúa y
   ajusta lo que viene. Las semanas pasadas quedan congeladas; cada ajuste
   crea una versión nueva del plan, con su justificación.

### Tres niveles de detalle

El detalle disminuye con la distancia en el tiempo:

| Horizonte | Detalle |
|---|---|
| Próxima semana | Sesiones concretas (día, clase, tipo, km, zona, terreno) |
| Resto del mesociclo actual | Objetivos semanales (volumen, nº de sesiones por clase, carga/descarga) |
| Mesociclos futuros | Esqueleto (objetivo, fechas, carga objetivo) |

Cada semana la siguiente baja del nivel 2 al 1; al cerrar un mesociclo, el
siguiente baja del nivel 3 al 2.

## Evaluación semanal: adherencia y progreso

Son dos preguntas distintas:

- **Adherencia** — ¿hice lo que decía el plan? (volumen, sesiones, zonas).
- **Progreso** — ¿me estoy adaptando? Se puede cumplir el plan al 100% y
  no mejorar. Fuentes:
  - **Tests de control** al final de cada mesociclo (ej. test de umbral o
    5K en llano), incluidos en el plan como sesiones.
  - **Indicadores pasivos** desde los datos de Garmin (ej. ritmo a FC fija
    en rodajes Z2 en llano). En trail el ritmo no es comparable por el
    desnivel: los indicadores salen de sesiones en llano o de un ritmo
    ajustado por desnivel calculado por nosotros.

## Reglas de ajuste

El perfil de metodología, además de describir cómo es un plan válido, define
**cómo reaccionar** a lo que pasó: `condición → acción`.

- Basadas en autores. Los autores rara vez dan números absolutos; se
  expresan en **porcentajes** relativos a mi propia línea base (ej. "cada
  mesociclo, si el test mejora, aumentar la carga un X%"). Esto hace que
  el mismo perfil se adapte a mí sin reescribirlo.
- `accion` es una lista cerrada (Enum): `progresar`, `repetir_microciclo`,
  `adelantar_descarga`, `extender_mesociclo`, ... El motor determinista
  decide qué acción toca; el LLM solo la concreta. Nunca inventa una
  reacción fuera de la lista.
- Cada regla declara su `origen`: `autor` (tal cual la fuente) o `propio`
  (mi interpretación numérica de una indicación cualitativa del autor).

## Arquitectura (resumen)

```
VPS Hostinger · docker-compose
n8n ── cron semanal ──▶ POST /semana/ajustar ─┐
    └─ manual ────────▶ POST /plan ───────────┤
                                              ▼
                        pb-coach: API mínima
                          ├─ sync (MCP, sin LLM) ◀── garmin-mcp ◀── Garmin Connect
                          ├─ agente LLM (propone)
                          ├─ motor determinista (decide)
                          ├─ perfiles YAML (metodología)
                          ├─ PostgreSQL (planes versionados, sesiones, ejecuciones)
                          └─ publicar (MCP, sin LLM) ──▶ garmin-mcp ──▶ reloj
n8n ◀── resultado ── Telegram
```

- `docker-compose` con tres servicios (`n8n`, `pb-coach`, `garmin-mcp`) en
  el VPS de Hostinger.
- `pb-coach` y `garmin-mcp` no se exponen a internet; solo n8n llama a
  `pb-coach`, con un token compartido.
- Garmin entra y sale solo por código determinista; el LLM trabaja con datos
  ya validados por `core/` (Pydantic) y agregados por `calculator.py`.

## Decisiones tomadas

- **Datos**: Garmin vía [Taxuspt/garmin_mcp](https://github.com/Taxuspt/garmin_mcp);
  Strava descartado por su política de API con IA (ver `decisions.md`).
- **Metodologías**: "Training for the Uphill Athlete" (House & Johnston) y
  "Trail Running: ciencia y entrenamiento" (Nacho Martínez), transcritas a
  mano; un perfil activo por plan.
- **Host**: VPS de Hostinger, junto a n8n.

## Fuera de alcance

- Múltiples usuarios, autenticación de usuarios, interfaz web.
- Otros deportes (calistenia, ciclismo).
- Generación de metodología por el LLM.
