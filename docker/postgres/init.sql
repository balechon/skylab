-- Se ejecuta una sola vez, cuando el volumen de Postgres está vacío.
-- Crea la base de skylab con su propio usuario; la contraseña llega por
-- variable de entorno (definida en .env), nunca escrita aquí.

\getenv skylab_password SKYLAB_DB_PASSWORD

CREATE USER skylab WITH PASSWORD :'skylab_password';
CREATE DATABASE skylab OWNER skylab;

-- Solo su dueño puede conectarse.
REVOKE CONNECT ON DATABASE skylab FROM PUBLIC;
GRANT CONNECT ON DATABASE skylab TO skylab;
