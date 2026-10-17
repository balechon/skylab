-- Se ejecuta una sola vez, cuando el volumen de Postgres está vacío.
-- Crea la base de pb-coach con su propio usuario; la contraseña llega por
-- variable de entorno (definida en .env), nunca escrita aquí.

\getenv pb_coach_password PB_COACH_DB_PASSWORD

CREATE USER pb_coach WITH PASSWORD :'pb_coach_password';
CREATE DATABASE pb_coach OWNER pb_coach;

-- Solo su dueño puede conectarse.
REVOKE CONNECT ON DATABASE pb_coach FROM PUBLIC;
GRANT CONNECT ON DATABASE pb_coach TO pb_coach;
