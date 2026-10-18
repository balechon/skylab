# Servicio de Notion (skylab-notion): Notion es la interfaz del atleta.
#
#   Notion → SKYLAB   ficha del atleta, casillas Evaluar / Recalcular de cada
#                     semana y comentarios de las sesiones
#   SKYLAB → Notion   el plan (semanas y sesiones), lo realizado en Garmin y
#                     el feedback de cada ajuste semanal
#
# Consulta Notion cada pocos minutos (no hay webhooks: exigirían exponer una
# URL pública). Solo usa la API de Notion y la de SKYLAB; Notion se puede
# sustituir sin tocar el agente. Ver docs/decisions.md.
