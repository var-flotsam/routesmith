# CLAUDE.md

Working rules for Starboard Routing (repo `routesmith`). `HANDOFF.md` says what the product is and what to
build next; this file says how work is done here. If `CLAUDE.local.md` exists
on this machine, its rules take precedence over everything below.

## What this is

Starboard Routing re-sequences residential collection routes for automated side-loader
trucks (right-side arm) and shows the current route against the optimized one
on a map. Monorepo: `apps/api` (FastAPI), `apps/worker` (arq), `apps/web`
(React + MapLibre), `packages/solver`, `packages/geo`, `packages/export`.
Python 3.12 with `uv`; TypeScript with `pnpm`. Licence: FSL-1.1-ALv2 (see
`LICENSE.md`); do not add code under licences incompatible with it (GPL/AGPL
dependencies are out).

## Start of every session

1. Read `HANDOFF.md`, `docs/CLEANROOM.md`, and the last entry in
   `docs/HANDOFF-log.md`. Where they differ, `docs/CLEANROOM.md` wins over `HANDOFF.md`.
2. `git status` must be clean; work on a branch, never on `main`.
3. Confirm the pre-commit hook is active: `git config core.hooksPath` prints
   `.githooks`. If not, run `scripts/install-hooks.sh` before anything else.

## Commands

```
uv sync --all-packages                 # Python deps
(cd apps/web && pnpm install)          # web deps
docker compose up -d db redis          # local Postgres/PostGIS and Redis
docker compose up --build              # the whole stack: API on :8000 and the worker
docker compose run --rm api python -m starboard.api.demo you@example.com   # demo route for you
uv run alembic upgrade head            # migrations
uv run pytest                          # all Python tests
uv run pytest packages/solver -m property   # solver property tests only
uv run ruff check . && uv run ruff format --check . && uv run mypy
(cd apps/web && pnpm test && pnpm lint && pnpm typecheck)   # pnpm via corepack
uv run starboard score data/demo/stops.csv       # baseline scorecard, no solve
uv run starboard optimize data/demo/stops.csv    # full run from the CLI
```

CI runs all of the above plus `gitleaks` and `scripts/check-banned-terms.sh`.
A red CI is never merged, and a check is never skipped or marked allowed-to-
fail to get a merge through.

## Invariants (the solver's hard constraints)

Every solution the solver returns, in tests or in production, satisfies all
of these. They are property-tested in `packages/solver/tests/test_properties.py`
on random synthetic street grids and on the demo town; invariant 5 is
property-tested in `packages/solver/tests/test_fleet.py`, and
`check_route_set` re-checks every route set before it is returned.

1. Every serviced cart is on the truck's right at the moment of service.
2. No travel against a one-way street.
3. No U-turn where the configured rules forbid it.
4. Route starts at the yard, visits a disposal site before the end (and
   whenever capacity would be exceeded), and ends at the yard.
5. When an area is split among N trucks: exactly N routes, each serving at
   least one stop; every servable stop served by exactly one route; all
   routes start and end at the shared yard and use the shared disposal site.

A change that makes a property test fail is wrong. Do not weaken, skip, or
reparameterize a property test to make it pass; fix the solver or raise it
with the owner.

## Code rules

- **No magic numbers.** Every tunable (turn penalties, speeds, snapping
  tolerance, time limits) lives in `packages/solver/defaults.py` with a
  one-line reason and a public citation where one exists.
- **Solver is pure.** `packages/solver` does no network or file I/O and has
  no dependency on the API or database. It takes a graph and stops, returns a
  sequence and a scorecard. Same input and seed give the same output.
- **Geo is the only place OSM and geocoders are touched.** Cached under
  `cache/` (git-ignored). Record the OSM snapshot date on every run.
- **Org scoping is enforced in the API layer**, on every query, and tested:
  a user in one organization can never read another's routes, runs, exports
  or permalinks. Add the cross-org negative test with every new endpoint.
- **Typed everywhere.** pydantic models at every boundary; `mypy --strict`
  on packages; no `Any` without a comment.
- **Errors are rows, not crashes.** Anything wrong with an uploaded stop
  (bad address, ambiguous snap, outside the area) becomes a review-queue item
  with a reason. The importer never raises on user data.
- **Frontend state** comes from the API through TanStack Query; no duplicated
  domain logic in the browser. Scorecard numbers are computed once, server-
  side, and displayed.
- **Exports are deterministic.** The same run produces a byte-identical CSV
  and a visually identical PDF; snapshot-test both.

## Data rules

- Nothing from any customer, real or prospective, is committed. Ever.
- The only addresses in the repo are the public demo set in `data/demo/`,
  whose `PROVENANCE.md` names the source, licence and download date.
- No OSM extracts, geocoder responses, secrets, `.env` files, or `cache/` in
  git. `gitleaks` runs in CI; if it fires, rotate the secret, don't just
  remove the line.
- Personal names of contributors do not appear in code, docs, commit
  messages, or the licence notice. Author identity is the repo-local git
  config (a handle and a noreply address). Copyright holder is "var-flotsam"
  until the owner says otherwise.

## Writing and naming

- Comments and docs describe this system in the present tense. No references
  to prior art, earlier versions, other projects, or where an idea came from
  unless it is a public paper or library, cited by link.
- Names say what things are: `required_arc`, `turn_penalty`, `review_item`.
  No abbreviations that need a glossary.
- Domain vocabulary: *cart* (the bin), *stop* (a cart's location), *pass*
  (one traversal of one street segment in one direction), *curb side*
  (left/right relative to travel direction), *dead-head* (driving a segment
  without servicing it), *run* (one solver execution), *street unit* (a stretch of one street with
all its required passes, which one truck serves), *district* (the street
units one truck serves when an area is split), *scorecard* (the
  measures for a route), *current* vs *optimized* (never "before/after" in
  the UI; "current" is what the driver does today).

## Pull requests

- One concern per PR, under ~400 lines of diff where possible. Tests in the
  same PR as the change.
- Description states the cause or motivation, what changed, and how it was
  verified. Link the HANDOFF phase or issue.
- Branch names: `feat/<area>-<short>`, `fix/<area>-<short>`, `chore/<short>`.
- Commit messages: imperative, under 72 characters, body explains why.
- Never force-push `main`. Never merge your own PR without CI green.

## Decisions

Anything listed in `HANDOFF.md` §6 is the owner's call: ask, don't assume.
Architectural choices beyond that get a short ADR in `docs/adr/` (context,
decision, consequences) in the same PR.

## End of every session

Append to `docs/HANDOFF-log.md`: date, what was done (with PR numbers), what
is next, what is blocked and on whom. Leave `main` deployable.
