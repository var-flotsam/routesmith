# apps/web

The web app: React, Vite, TanStack Query and MapLibre. `pnpm -C apps/web dev` serves it
on :5173 and proxies `/api` to the API on :8000. After an API change, regenerate the
types: `uv run python -m starboard.api.openapi apps/web/openapi.json && pnpm -C apps/web api-types`.

`pnpm -C apps/web build:demo` builds the static demo (`docs/adr/0007-static-demo.md`): one page
showing the precomputed demo result in `data/demo/result/`, with no sign-in and no API.
`pnpm -C apps/web dev:demo` serves it locally. `STARBOARD_WEB_BASE` sets the path the demo is
served under, such as `/routesmith/` (`/` by default); the normal build ignores it.
