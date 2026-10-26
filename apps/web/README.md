# apps/web

The web app: React, Vite, TanStack Query and MapLibre. `pnpm -C apps/web dev` serves it
on :5173 and proxies `/api` to the API on :8000. After an API change, regenerate the
types: `uv run python -m starboard.api.openapi apps/web/openapi.json && pnpm -C apps/web api-types`.
