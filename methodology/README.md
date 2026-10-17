# Perfiles de metodología

Un **perfil** es la transcripción manual de la metodología de un autor o
framework de entrenamiento a un YAML estructurado que el motor determinista
(`core/`) puede cargar, validar y citar.

Solo un perfil está activo por plan. No se combinan reglas de distintos
autores dentro de un mismo plan — evita conflictos entre metodologías
incompatibles.

## Por qué transcripción manual

El LLM nunca transcribe metodología a reglas por su cuenta. Tú lees la
fuente (libro, paper, apuntes) y escribes el YAML. Esto es lo que garantiza
que el sistema "nunca inventa metodología, la aplica": si una regla no está
en un perfil, el sistema no la conoce y no puede usarla.

## Convención de IDs de regla

Cada regla debe tener un ID único, estable y citable, con el formato:

```
<AUTOR>-<CATEGORIA>-<NNN>
```

- `AUTOR`: abreviatura corta del autor/framework (ej. `LYDIARD`, `DANIELS`).
- `CATEGORIA`: tipo de regla — `CARGA`, `PROGRESION`, `DESCANSO`,
  `SECUENCIA`, `INTENSIDAD`, etc.
- `NNN`: número correlativo con ceros a la izquierda (`001`, `002`, ...).

Ejemplo: `LYDIARD-PROGRESION-003`.

Este ID es el que el agente cita textualmente al justificar cualquier
decisión del plan. Si no hay un ID de regla detrás de una decisión, esa
decisión no debería estar en el plan.

## Cómo añadir un perfil nuevo

1. Copia `profiles/_template.yaml` a `profiles/<autor>.yaml`.
2. Rellena los campos con las reglas reales de la fuente, cada una con su ID.
3. Valida que carga: `uv run pytest tests/core/test_loader.py` prueba
   automáticamente todos los perfiles de `profiles/` (`core/loader.py`).

## Borradores

Un perfil en transcripción vive en `borradores/` (por ejemplo,
`borradores/uphill_athlete.yaml`). El sistema solo carga `profiles/`, así que
un borrador incompleto nunca se usa para planificar. Al terminarlo se mueve a
`profiles/` y los tests lo validan contra el modelo.
