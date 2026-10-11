# Imágenes de PB_coach. Un workspace de uv, una imagen por servicio; cada una
# instala solo su paquete y sus dependencias:
#
#   api   pb-coach-api   API + agente LLM (anthropic, fastapi). Sin MCP.
#   sync  pb-coach-sync  sync de Garmin (mcp). Sin FastAPI ni anthropic.
#   test  todo el workspace + grupo dev, para correr pytest.
#
# docker compose construye cada una con su `target`.

FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages ./packages

RUN useradd --create-home --uid 1000 app


# ---------- API + agente ----------
FROM base AS api

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package pb-coach-api --no-dev --no-editable

COPY methodology ./methodology

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

# Aplica las migraciones pendientes antes de servir la API.
CMD ["sh", "-c", "alembic -c packages/persistence/alembic.ini upgrade head && exec uvicorn pb_coach.api.app:app --host 0.0.0.0 --port 8000"]


# ---------- sync de Garmin ----------
FROM base AS sync

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package pb-coach-sync --no-dev --no-editable

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "pb_coach.sync.app:app", "--host", "0.0.0.0", "--port", "8000"]


# ---------- tests ----------
FROM base AS test

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --all-packages

COPY methodology ./methodology
COPY tests ./tests

CMD ["pytest", "-q"]
