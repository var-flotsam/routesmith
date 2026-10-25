# Starboard Routing: handoff

Starboard Routing ("Starboard" in conversation; repo `routesmith`) is a web product that re-sequences residential collection routes for
automated side-loader trucks whose arm is on the right side only, and shows the
driver's current route against the optimized one, side by side, on a map. The
buyer is a small or mid-sized waste hauler (5 to 60 residential routes) that
bought side-loaders and is still running the routes it drew for rear-loaders.

This file is the single source of truth for a Claude Code session working on
the project. Read it, then `docs/CLEANROOM.md`, then `CLAUDE.md`.

Product name: Starboard Routing. Repository: `routesmith`. Python package and CLI: `starboard`.

---

## 1. The problem, from first principles

A rear-loader with a crew can serve both curbs in one pass. An automated side
loader (ASL) has one arm, on the right, and a single driver who never leaves
the cab. The truck can only pick up a cart that sits on the curb to the
truck's right, which depends on the direction the truck is **facing**. On a
two-way street that means one pass per curb. Routes drawn for rear-loaders
therefore have the ASL driving every two-way street twice anyway, in whatever
order the old sheet listed, with left turns, U-turns and dead-heading nobody
planned.

What a hauler wants to know:

1. In what order should the truck drive the streets so every cart is on the
   right, the truck never goes the wrong way on a one-way, left turns and
   U-turns are rare, and the total time is minimal?
2. How much better is that than what the driver does today? (This is the
   purchase decision. The product must answer it visually and numerically
   before anyone pays.)
3. What does the driver actually get handed on Monday morning?

### Hard constraints (never violated in any output)

- Every serviced cart is on the truck's right side at the moment of service.
- No travel against a one-way street.
- No U-turn where the road geometry does not allow it (configurable: dead ends
  and cul-de-sacs always allowed).
- Route starts at a yard, ends at a yard, and visits a disposal site before
  the end (and when a capacity is given, whenever the load would exceed it).
- When an area is split into N routes: exactly N routes, each serving at least
  one stop; every stop served by exactly one route; every route starts and
  ends at the shared yard and uses the shared disposal site.

### Soft costs (minimized, weights visible to the user)

- Drive time, from OSM speed limits or a flat urban speed.
- Left turns across traffic, U-turns, and reversing (reversing default: off).
- Dead-heading (driving a street without servicing it).
- Mid-block turnarounds.

### Out of scope for v1

Time windows, commercial front-load or roll-off, live GPS tracking, mid-route
dynamic re-sequencing, and, within an area split into several routes, trucks
with different profiles or more than one yard or disposal site. Each is a
later product; do not design them in now. Splitting one area into a given
number of routes is in scope, as `docs/adr/0003-multi-route.md` describes.

---

## 2. How the product works

### 2.1 User journey

1. **Sign up, create an organization.** One org per hauler; users belong to an
   org; roles are owner, planner, viewer.
2. **Create a route.** Name, truck profile (arm side, can reverse, capacity),
   yard, disposal site(s). Address or lat/lon for each location.
3. **Upload the current stop list.** CSV or XLSX. The importer maps columns
   interactively (address, or lat/lon, optional sequence number, optional
   cart count, optional notes). Stops are geocoded, snapped to the nearest
   OSM street edge, and assigned a curb side. Anything ambiguous (snapped to
   two candidate streets, geocode confidence low, address on a corner) goes to
   a **review queue** the planner clears on the map by clicking the right
   street. Nothing proceeds with unreviewed stops.
4. **Run.** The solver runs as a background job. The UI shows progress and an
   estimate. Typical residential route (600 to 1,200 stops): under three
   minutes.
5. **Compare.** The result page is the product:
   - Map with two layers, **Current** and **Optimized**, toggled or split
     left/right. Each street pass drawn with direction arrows. Wrong-side
     pickups in the current route highlighted.
   - **Playback**: a scrubber drives two truck markers at the same simulated
     speed; the viewer watches the optimized one finish first.
   - **Scorecard** with the same measures for both routes and the delta:
     distance, drive time, left turns, U-turns, reversing segments, wrong-side
     pickups, dead-head distance, number of street passes.
   - **Stop table**: current sequence, new sequence, street, side, and a
     filter for stops that moved most.
   - **Permalink** to this comparison (org-private by default; a "share
     read-only link" toggle for sending to a general manager).
6. **Export.** Driver route sheet as PDF (ordered street segments with
   side-of-street, turn-by-turn, map thumbnail per page), CSV of stops in new
   order, GPX/KML of the path. These are what the dispatcher prints Monday.
7. **Re-run.** Edit the truck profile or weights, re-run, compare runs.

### 2.2 The "current route" baseline

The comparison is only honest if the baseline is what the driver actually
does. Build the baseline from the uploaded sequence as a *driven path*: from
each stop to the next by shortest legal road path, respecting one-ways, with
the truck's facing direction tracked so wrong-side pickups are counted, not
assumed away. Make the baseline construction rules visible in the UI, because
a buyer will ask how the "before" numbers were produced.

### 2.3 Solver model

Model the street network as a directed graph of **(segment, direction)**
states. Each curb with carts is a **required arc** (that segment, in the
direction that puts the curb on the right). Unserviced streets are optional
arcs. Turns are costs on transitions between arcs, computed from edge
bearings, with one-way and U-turn rules as infeasible transitions. This is a
directed rural postman problem with turn penalties.

Solve with OR-Tools routing on a line-graph transformation (each required arc
becomes a node; arc-to-arc cost = traversal + turn + shortest legal path
between them), warm-started from the baseline order, followed by a local
search (2-opt / or-opt on the arc sequence with the turn model). Time limit
configurable; deterministic for a fixed seed.

Property tests (hypothesis) assert the hard constraints on every solution the
solver ever returns, on random synthetic grids. These tests gate every merge.

### 2.4 Data

- Street network: OpenStreetMap via OSMnx, cached per bounding box, refreshed
  monthly. Record the OSM snapshot date on every run.
- Geocoding: Nominatim (self-hosted or the public endpoint with rate limits)
  for v1; Google or Mapbox behind an interface later.
- Demo dataset: address points from OpenAddresses for one small town, with a
  synthetic "current order" sorted by street name and house number, as route
  sheets commonly are. Committed to the repo under `data/demo/`. No customer
  data is ever committed.

---

## 3. Architecture

| Layer | Choice |
| --- | --- |
| API | FastAPI, pydantic v2, OpenAPI published |
| Database | Postgres 16 + PostGIS; Alembic migrations |
| Jobs | Redis + arq worker; one job type `solve_run` |
| Solver | `starboard.solver` package, pure Python + OR-Tools, no I/O; callable from CLI and worker |
| Frontend | TypeScript, React, Vite, MapLibre GL, TanStack Query |
| Auth | Email magic link + GitHub/Google OAuth; sessions in Postgres; org-scoped row-level checks in the API layer |
| Files | S3-compatible object storage for uploads and PDF exports |
| Packaging | Docker Compose for dev; one image per service |
| Deploy | Fly.io or Railway, GitHub Actions on merge to `main`; staging and production |
| Observability | Structured JSON logs, `/healthz`, Sentry, run-duration and solver-quality metrics |

Repo layout:

```
routesmith/
  apps/api/          FastAPI app, routers, auth, org scoping
  apps/worker/       arq worker, job definitions
  apps/web/          React app
  packages/solver/   graph build, baseline, model, local search, scoring
  packages/geo/      OSM fetch and cache, geocoding, snapping, curb assignment
  packages/export/   PDF route sheet, CSV, GPX/KML
  data/demo/         public demo dataset and its provenance
  docs/              CLEANROOM.md, architecture, ADRs, pricing notes
  infra/             compose, Dockerfiles, deploy config
```

Every tunable (turn penalties, speeds, snapping tolerance, solver time limit)
lives in `packages/solver/defaults.py` with a one-line reason and, where
applicable, a citation to a public source (e.g. a DOT turning-movement delay
table). No magic numbers.

---

## 4. Build order

Each phase ends with a PR, green CI, and a line in `docs/HANDOFF-log.md`.

1. **Foundation.** Repo, `LICENSE.md` (FSL-1.1-ALv2), `CLEANROOM.md`, CI skeleton,
   demo dataset with provenance file. Graph builder: OSM bbox to
   (segment, direction) graph; curb assignment from stop point to edge.
2. **Baseline and scoring.** Driven-path reconstruction of an uploaded order;
   scorecard measures; CLI `starboard score stops.csv`.
3. **Solver v1.** Required-arc model, OR-Tools on the line graph, yard and
   disposal site with capacity, hard constraints as property tests, local
   search, CLI `starboard optimize`. Then multiple routes, as
   `docs/adr/0003-multi-route.md` describes: street units, a partition into N
   contiguous districts, each district solved by the single-route solver, an
   exchange loop between neighbouring districts, the balanced-total objective
   (with longest-route and total as options), invariant 5 and an independent
   route-set checker, a scale benchmark, and
   `starboard optimize --trucks N`. With N = 1 only the single-route solver
   runs.
4. **API and worker.** Orgs, users, routes, uploads, runs, results; arq job;
   Compose stack; schemathesis against the OpenAPI spec.
5. **Web v1.** Sign-in, route setup, upload with column mapping, review queue
   on the map, run status, current-route map, stop table. **Deploy to a
   public URL at the end of this phase**, demo route preloaded.
6. **Comparison view.** Optimized layer, split view, playback, scorecard
   deltas, permalinks, share links.
7. **Exports.** PDF route sheet, CSV, GPX/KML.
8. **Sellable.** §5 below.

---

## 5. What "shippable and sellable" requires

Shippable means a hauler can sign up and get a route sheet without talking to
you. Sellable means they can pay, trust you with their addresses, and you can
support them. Everything below is a checklist, not a suggestion.

### Product

- [ ] Onboarding that takes a new user from sign-up to a comparison on the demo
      route in under five minutes, with no documentation.
- [ ] Import handles the messy real world: Excel with merged headers, addresses
      with unit numbers, "corner of X and Y", duplicate rows, stops outside the
      service area. Every failure is a row in the review queue, never a crash.
- [ ] Review queue is fast: keyboard shortcuts, next-unresolved, bulk accept
      when confidence is high.
- [ ] Truck profiles: arm side (right for v1; left as a flag for other markets),
      reversing allowed, capacity in carts, max route duration.
- [ ] Run history per route; compare any two runs.
- [ ] Driver route sheet PDF that a 60-year-old driver can follow in a cab.
      Test it with one.
- [ ] Empty states, error states, loading states for every screen.

### Trust and data

- [ ] Privacy policy and terms of service (templates are fine; a lawyer reads
      them before the first paid customer). Customer addresses are personal
      data; say what you keep, for how long, and how to delete it.
- [ ] Org data isolation enforced in the API layer and tested: a user in org A
      cannot read a run in org B, including by permalink or export URL.
- [ ] Delete organization = everything gone, including uploads and exports in
      object storage. Tested.
- [ ] Encrypted at rest (managed Postgres and S3 do this; say so), TLS
      everywhere, secrets in the host's secret store, no secrets in the repo
      (gitleaks in CI).
- [ ] Backups: nightly Postgres snapshot, restore tested once and documented.
- [ ] Audit log: who uploaded, ran, exported, shared, deleted.
- [ ] A status page and a support address that a human reads.

### Money

- [ ] Stripe Billing: per-active-route per month, with a free tier of one route
      (the demo) so the comparison view sells itself. Annual option.
- [ ] Usage metering tied to runs, not seats; haulers have few users and many
      routes.
- [ ] Invoices with the hauler's legal name and address; many will pay by
      check or PO, so an invoice-me path is needed, not just cards.
- [ ] Pricing page with three honest numbers and a "talk to us" for fleets over
      60 routes.

### Operations

- [ ] Staging environment that mirrors production; deploy to staging on every
      merge, production on tag.
- [ ] Alerts: error rate, job queue depth, solver p95 duration, failed exports.
- [ ] Runbook: a run is stuck, a geocoder is down, OSM fetch fails, a customer
      asks for their data.
- [ ] Rate limits on uploads and runs per org.
- [ ] Load test: 20 concurrent runs of 1,000 stops on the staging stack.

### Go to market (so engineering choices serve it)

- The sales motion is the comparison view. Every demo starts with "upload your
  worst route." Make the upload-to-comparison path the most polished thing in
  the product.
- First ten customers come from direct outreach to haulers who recently bought
  ASLs (truck dealers and state solid-waste associations publish this), with
  a free comparison on one route as the opener.
- Integrations with hauler back-office systems (routing and billing software
  used in this industry) are the v2 moat. Design the import/export layer
  behind interfaces so a connector is a module, not a rewrite.

---

## 6. Open decisions for the owner

Record each as an ADR in `docs/adr/` when decided.

1. Licence: decided. The whole repository is under FSL-1.1-ALv2 (see
   `LICENSE.md`): source-available, no competing commercial use, each version
   becomes Apache-2.0 two years after release. Record as ADR-0001.
2. Geocoder: self-hosted Nominatim (free, slower, you run it) vs. a paid API
   (fast, per-call cost, terms restrict caching). Recommendation: Nominatim
   for v1 with the interface in place.
3. Company formation, business bank account, and Stripe account need a legal
   entity. Do this before §5 "Money".
4. Domain purchase and a trademark clearance search on "Starboard Routing" before launch.
5. Multiple routes (ADR-0003). Decided: the objective is least total route
   time with every route within a balance margin of the average. Still open,
   with the default used until decided: the balance margin (10%); whether a
   truck profile's maximum route duration bounds every route (yes); the
   multi-route time budget (three minutes per route); "best found" with a
   bound and gap in place of "optimal" (yes); one truck profile for all
   trucks (yes); turning around inside the yard and disposal site is free and
   is not a street U-turn (yes).

---

## 7. Working rules for the session

- Read `docs/CLEANROOM.md` before writing code. Its rules override anything
  else in this file.
- Small PRs, one concern each, tests with every change. CI must be green to
  merge.
- The solver's hard constraints are property-tested. A change that makes a
  property test fail is wrong, not the test.
- Every number in `defaults.py` has a reason next to it.
- Never commit customer data, real addresses outside the demo set, API keys,
  or OSM extracts (they are cached, not versioned).
- Update `docs/HANDOFF-log.md` at the end of every session: what was done,
  what is next, what is blocked.
