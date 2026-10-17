# Entradas del sistema

Qué necesita el agente para planificar de forma coherente, de dónde sale cada
dato y qué parte comprueba el código. Diseño cerrado el 2026-10-17, antes de
implementar la ficha del atleta, el calendario de carreras y Notion.

## Dos fuentes, dos naturalezas

| Fuente | Qué contiene | Por qué ahí |
|---|---|---|
| **YAML en git** (`methodology/profiles/`) | La metodología de un autor: reglas, secuencias de bloques, ajustes, reglas por prioridad de carrera y tests | Cambia poco, se versiona con git, los tests la validan y su estructura es rígida |
| **Notion** (fase B) | Los datos del atleta: ficha, carreras, tests, semanas y entrenamientos | Cambian a menudo y los decide el atleta; Notion es cómodo para editarlos |

El agente y la API **no hablan con Notion**. El servicio `notion` lee los
datos y se los envía a la API, que guarda una copia con cada ejecución (con
qué datos se planificó). Notion es sustituible sin tocar el agente.

## Calendario de carreras

Cada carrera tiene nombre, fecha, distancia, D+, terreno y **prioridad**:

| Prioridad | Significado | Tratamiento en el plan |
|---|---|---|
| **A — Objetivo** | Rendir al máximo | Es la fecha objetivo del modo competición: bloque específico y puesta a punto |
| **B — Competir** | Hacerlo bien sin ser la principal | Descarga ligera antes y recuperación después, sin romper la progresión hacia la A |
| **C — Participar** | Por diversión o como entrenamiento | Una sesión más de la semana (por ejemplo, sustituye al fondo), sin descarga |

- Las carreras cuentan **en los dos modos**. En construcción no hay A; las B y
  las C se integran en la semana como una sesión más.
- El tratamiento de cada prioridad (días de descarga antes de una B,
  recuperación después, qué sesión sustituye una C) **es metodología**: sale
  de una sección `reglas_carreras` del perfil, no del LLM. Si el perfil no la
  define y hay carreras B o C en el horizonte, el sistema avisa en lugar de
  improvisar, igual que con `secuencias_bloques`.

## Ficha del atleta

| Dato | Uso |
|---|---|
| Perfil activo, modo y objetivo del ciclo | Qué metodología y hacia dónde |
| Disponibilidad por día (días libres, máximo de horas) | Restricción dura |
| Terrenos disponibles (pista, montaña solo fin de semana…) | Restricción dura |
| FC máx., FC en reposo, umbral aeróbico y anaeróbico | Zonas propias; el reloj recibe pulsaciones exactas |
| Volumen máximo histórico y lesiones | Contexto para la progresión y la prudencia |

## Tests

Fecha, tipo (por ejemplo, umbral aeróbico) y resultado. Alimentan las zonas
propias y las métricas de progreso (`mejora_test_pct`), que hoy quedan como
no evaluables.

## Semanas y entrenamientos

- **Semanas**: comentario general, casillas Evaluar y Recalcular, y el
  feedback que escribe el agente.
- **Entrenamientos**: una fila por sesión con lo planificado, lo realizado,
  RPE, sensación y el comentario del atleta.

## Lo que comprueba la guardia

- Ninguna sesión en un día no disponible ni más larga que el máximo de ese día.
- Ninguna sesión en un terreno no disponible.
- Cada carrera C aparece en su fecha como sesión, y ese día no hay otra.
- Las B y las C se tratan según `reglas_carreras`, citando su regla.
- En competición, la fecha objetivo es la de la carrera A.

## Orden de trabajo

1. Este documento.
2. El atleta transcribe Uphill Athlete al YAML; en paralelo se amplía el
   modelo con lo que el libro necesite (fuerza, caminata, zonas por umbral,
   `reglas_carreras`, tests).
3. Ficha del atleta y calendario de carreras en el código, con la guardia.
4. Notion: las cinco bases y el servicio que las conecta.
