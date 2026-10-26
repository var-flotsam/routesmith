# One image for the API, the worker and migrations; the command picks which runs.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv

# pyosmium links against expat, which the slim image leaves out.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

# Dependencies first, so code changes reuse this layer.
COPY pyproject.toml uv.lock ./
COPY packages/solver/pyproject.toml packages/solver/pyproject.toml
COPY packages/geo/pyproject.toml packages/geo/pyproject.toml
COPY packages/export/pyproject.toml packages/export/pyproject.toml
COPY apps/cli/pyproject.toml apps/cli/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
RUN uv sync --frozen --no-dev --all-packages --no-install-workspace

COPY packages packages
COPY apps apps
COPY alembic.ini ./
# The public demo set, for `python -m starboard.api.demo`.
COPY data/demo data/demo
RUN uv sync --frozen --no-dev --all-packages

RUN useradd --create-home starboard && mkdir -p /app/cache && chown starboard /app/cache
USER starboard

EXPOSE 8000
CMD ["uvicorn", "starboard.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
