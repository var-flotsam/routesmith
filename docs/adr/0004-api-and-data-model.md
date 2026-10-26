# ADR-0004: The API, its data model, sign-in and org scoping

Date: 2026-10-26

## Context

Phase 4 (HANDOFF §4) puts the solver behind an API and a background worker:
organizations, users, routes, uploads, runs and results. HANDOFF §3 fixes the
stack (FastAPI, Postgres 16 with PostGIS, Alembic, Redis with arq,
S3-compatible storage, magic-link and OAuth sign-in, sessions in Postgres).
This ADR settles what sits inside that stack: the tables, how a request is
tied to one organization, how sign-in works, and how a run moves from upload
to result.

## Decision

### Packages

`apps/api` is the workspace package `starboard-api` (module `starboard.api`);
`apps/worker` is `starboard-worker` (module `starboard.worker`). Both depend
on `starboard-solver` and `starboard-geo`. The stop-file reader moves from
`apps/cli` into `starboard.geo.stop_file`, so the CLI, the API and the worker
read stop files the same way.

Database access is SQLAlchemy 2 (MIT) in async mode on asyncpg
(Apache-2.0), with GeoAlchemy2 (MIT) for PostGIS columns and Alembic (MIT)
for migrations. psycopg is not used: it is LGPL-3.0, and ADR-0001 keeps the
dependency tree to permissive licences. arq is MIT.

### Tables

Every row that belongs to a customer carries `org_id`. Ids are UUIDv4.

| Table | Holds |
| --- | --- |
| `organizations` | name |
| `users` | email (unique, stored lower-case) |
| `memberships` | org, user, role: `owner`, `planner` or `viewer` |
| `login_tokens` | SHA-256 of a magic-link token, email, expiry, used-at |
| `sessions` | SHA-256 of a session token, user, expiry, last seen |
| `routes` | org, name, truck profile (capacity in carts, maximum hours), yard and disposal site as PostGIS points |
| `uploads` | org, route, file name, object-store key, row counts |
| `stops` | org, upload, stop id, current sequence, current route id, point, street, state (`snapped`, `review`, `rejected`), segment and curb side once snapped, review reason |
| `runs` | org, route, upload, state (`queued`, `running`, `succeeded`, `failed`), trucks, objective, OSM snapshot date, solver version, timings, failure reason |
| `run_results` | run, current and optimized scorecards, optimized order per route, unserved stops with reasons, bound and gap (JSONB) |

Only hashes of tokens are stored, so a database copy cannot be used to sign
in. Scorecards are stored as the solver computes them; the browser only
displays them (CLAUDE.md, frontend state).

### Org scoping

A request resolves to one user from its session cookie, and to one
organization from the `org_id` in the path (`/orgs/{org_id}/...`) checked
against that user's memberships. Every query on an org-owned table goes
through a repository function that takes the resolved org and adds
`WHERE org_id = :org`; no router builds its own query on those tables. A row
in another organization answers 404, the same as a row that does not exist,
so ids leak nothing. Roles: viewers read; planners also upload, edit routes
and start runs; owners also manage members. Every endpoint ships with a test
that a user of another organization gets 404 (CLAUDE.md, org scoping).

### Sign-in

Magic link first. `POST /auth/magic-link` takes an email and always answers
202, whether or not the address has an account. It stores a hashed one-time
token that expires after `LOGIN_TOKEN_TTL` and sends the link through an
`EmailSender` interface (a console sender in development). Opening the link
consumes the token, creates the user on first sign-in, and sets a session
cookie (`HttpOnly`, `Secure`, `SameSite=Lax`) whose hash is in `sessions`,
expiring after `SESSION_TTL` without use. GitHub and Google OAuth come in
phase 5 with the sign-in pages, since they need client registrations under
the owner's accounts.

### Runs

`POST .../runs` checks that the upload has no stops left in review (HANDOFF
§2.1: nothing proceeds with unreviewed stops), writes a `queued` run, and
enqueues the arq job `solve_run` with the run id only. The worker loads the
route and stops, builds the network through `starboard.geo` (cached), runs
`solve_routes` and the current-route baseline in a process pool (the solver
is CPU-bound and synchronous), and writes `run_results` and the final state
in one transaction. A run that raises records `failed` with the reason. The
job timeout is the per-route solver ceiling times the number of trucks, plus
a margin for the network fetch.

### Files

Uploaded files go to an `ObjectStore` interface: S3-compatible in deployed
environments, a local directory in development and tests. The database keeps
only the key.

## Consequences

- Org scoping lives in one layer and is tested per endpoint, so a missed
  `WHERE` shows up as a failing negative test, not a data leak.
- The worker and API share the stop-file reader and the solver entry points
  the CLI already exercises, so the CLI remains the quickest way to check a
  solver change end to end.
- Database tests need Postgres with PostGIS. CI runs them against a
  `postgis/postgis:16` service container; locally they run under Docker
  Compose and are skipped with a reason when no database is reachable.
- New tunables (`LOGIN_TOKEN_TTL`, `SESSION_TTL`, the job timeout margin) are
  API settings, not solver tunables. They live in `starboard.api.settings`,
  each with a stated reason.
- Geocoding addresses waits on the owner's choice (HANDOFF §6, item 2); until
  then uploads need lon/lat columns.
