# Imágenes de SKYLAB. Un workspace de uv, una imagen por servicio; cada una
# copia e instala solo sus carpetas:
#
#   api   skylab-agent  core + persistence + agent (anthropic, fastapi). Sin MCP.
#   sync  skylab-sync   core + persistence + sync (mcp). Sin FastAPI ni anthropic.
#   test  todo el workspace + grupo dev, para correr pytest.
#
# El código se instala (no editable) en /src/.venv y los procesos corren
# desde /app: así solo se puede importar lo que la imagen tiene instalado.

FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1 \
    PATH="/src/.venv/bin:$PATH"

WORKDIR /src

# uv --locked necesita ver el pyproject de todos los miembros del workspace,
# aunque la imagen solo instale algunos.
COPY pyproject.toml uv.lock ./
COPY core/pyproject.toml core/
COPY persistence/pyproject.toml persistence/
COPY sync/pyproject.toml sync/
COPY agent/pyproject.toml agent/

RUN useradd --create-home --uid 1000 app


# ---------- API + agente ----------
FROM base AS api

COPY core core
COPY persistence persistence
COPY agent agent
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package skylab-agent --no-dev --no-editable

WORKDIR /app
COPY methodology ./methodology

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

# Aplica las migraciones pendientes antes de servir la API.
CMD ["sh", "-c", "alembic -c /src/persistence/alembic.ini upgrade head && exec uvicorn agent.api:app --host 0.0.0.0 --port 8000"]


# ---------- sync de Garmin ----------
FROM base AS sync

COPY core core
COPY persistence persistence
COPY sync sync
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package skylab-sync --no-dev --no-editable

WORKDIR /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "sync.app:app", "--host", "0.0.0.0", "--port", "8000"]


# ---------- tests ----------
FROM base AS test

COPY core core
COPY persistence persistence
COPY sync sync
COPY agent agent
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --all-packages

COPY methodology ./methodology
COPY tests ./tests

CMD ["pytest", "-q"]
