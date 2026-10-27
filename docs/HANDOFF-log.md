# Handoff log

## 2026-10-24

**Done (phase 1, local branches; PRs open once `main` is on GitHub)**

- `main`: README, FSL-1.1-ALv2 licence, dated `docs/CLEANROOM.md`, `.gitignore`.
- `chore/banned-terms-guard`: `scripts/check-banned-terms.sh`, `.githooks/`
  (pre-commit and commit-msg), `scripts/install-hooks.sh`. Verified it blocks a
  staged file, a commit message, and a missing list.
- `chore/repo-layout`: HANDOFF §3 layout, uv workspace (`starboard-solver`,
  `starboard-geo`, `starboard-export`), ruff, mypy --strict, pytest +
  hypothesis, CI with gitleaks and the banned-terms check.
- `feat/demo-dataset`: 754 address points in Byram, Greenwich, CT from the
  public-domain CT 9-1-1 Address Points, with a synthetic current order and
  `data/demo/PROVENANCE.md`.
- `feat/geo-state-graph`: OSM fetch with on-disk cache and OSM timestamp,
  (segment, direction) state graph with signed heading changes and U-turn
  flags, snapping and curb side, review items for anything undecidable.
  Tested on a 4x4 synthetic grid and on the demo town (690 of 754 stops snap;
  30 outside the network, 19 on the left of a one-way, 15 ambiguous).

**Next (phase 2)**

- Baseline: driven path through `current_sequence` by shortest legal path on
  the state graph, tracking facing direction to count wrong-side pickups.
- Scorecard measures and `starboard score data/demo/stops.csv`.
- Turn restrictions from OSM relations (OSMnx graphs do not carry them).
- Check whether stops snap to motorway or ramp segments; exclude them from
  snapping candidates if so.

**Blocked**

- (Resolved the same day: `main` pushed, `BANNED_TERMS` secret added, PRs
  #1 to #6 landed on `main` through #7.)

## 2026-10-25

**Done (phase 2, PRs #8 to #13)**

- #8: motorways and their ramps are drivable but never snap candidates (8
  demo stops had snapped to I-95 ramps).
- #9: OSM turn restrictions through a node mark forbidden transitions;
  through-way restrictions are counted, not applied.
- #10: cost model (OSRM car-profile speeds and turn costs), current-route
  baseline with facing direction and wrong-side pickups, scorecard, and
  property tests on random grids in `packages/solver/tests/test_properties.py`.
- #11: `starboard-cli` in `apps/cli` (ADR-0002) with `starboard score`.
- #12: ADR-0001 for the licence.

**Next (phase 3)**

- Required-arc model on the line graph with OR-Tools, warm-started from the
  baseline order; local search; `starboard optimize`.
- Yard and disposal sites on a route (start, end, capacity), for both the
  baseline and the solver.
- Divided roads: 19 demo stops are on the left of a one-way, some likely
  one carriageway of a two-carriageway street; snap them to the other
  carriageway when it has the same name.

**Blocked**

- Demo-town tests (`pytest -m demo`) and `starboard score data/demo/stops.csv`
  have not run since #8: the public Overpass server stopped answering this
  machine. Re-run both once it answers.

## 2026-10-25 (later)

**Done**

- #14: networks from a local OSM extract (Geofabrik); Overpass stopped
  answering this machine.
- #15: ADR-0003, multiple routes per area (districts first, then the
  single-route solver); scope change recorded in HANDOFF §1, §4, §6.
- #16: two-way OSM streets no longer split into one-ways; cut-off edge nodes
  are not dead ends.
- #17: current route driven street by street; wrong-side pickups cost 64 s;
  pick up in passing; low-density U-turns; route time on the scorecard.
  Byram: 91 km, 7.1 h, 712 stops, 30 wrong-side pickups.
- Owner kept the ADR-0003 defaults (HANDOFF §6 item 5).

**Next (phase 3)**

- Single-route solver with yard, disposal site and capacity, then the
  multi-route steps in ADR-0003's delivery list.
- `DISPOSAL_UNLOAD_TIME` needs a public figure.
- The synthetic demo order jumps between streets alphabetically (about 50 km
  of the 91 km); revisit once the solver exists.

**Blocked**

- Nothing.

## 2026-10-25 (phase 3, single route)

**Done**

- #19: connection costs between passes and places (SciPy Dijkstra, integer ms).
- #20: single-route optimizer on OR-Tools: required passes on the line graph,
  disposal visits when full, 2-opt / or-opt, optimal unload placement.
- #21: current route drives yard to yard and unloads when full.
- #22: `starboard optimize`, `data/demo/route.json` (Holly Hill transfer
  station as yard and disposal; 420 carts per load; 16 min per unload).
- #23: fixes for 13 review findings; solution limit 1,000 from a 1,200-stop
  benchmark (46 s).
- #24: the demo's current order is a rear-loader route; Byram 68 km / 7.3 h
  current against 39 km / 4.6 h optimized.

**Next**

- Multi-route steps from ADR-0003 (connection costs are done; street units
  and the district partition next).
- Speed up local search when OR-Tools is cut short (it can take most of the
  three minutes on large routes).
- Truck restrictions from OSM (`hgv=no`, `maxweight`); the Town restricts
  trucks on St. Roch Avenue, which OSM does not tag.
- The current route cannot turn round inside the yard or disposal site; the
  optimized route can.

**Blocked**

- Nothing.

## 2026-10-26 (phase 3, several routes)

**Done**

- #26 to #28: street units, the route objectives and bounds, the district
  partition.
- #29: `solve_routes`, the route-set checker (invariant 5), `--trucks N` and
  `--objective`.
- #30: the step that swaps street units between districts. Byram on 2 trucks
  goes from 16,475 s to 16,361 s in total, with the longest route from
  8,927 s to 8,671 s.
- #31: an optional `route_id` column. Each truck's current route is driven on
  its own and compared, as an area, with the optimized routes.
- #32: local search resumes where it found its last move: 110 s to 14 s on a
  600-stop grid.
- #33: compact plan-cost tables and the scale benchmark at 1,000 stops per
  truck (88 s, 12 min and 48 min for 1, 3 and 10 trucks).

**Decisions**

- At most 1,000 stops per truck per day (owner, 2026-10-26).
- With a `route_id` column and no `--trucks`, the area is split among as many
  trucks as there are current routes.
- 2-opt* tail exchange is not used, since a tail cuts across street units
  (ADR-0003).

**Next**

- Enforce the 1,000-stop limit in the solver; the owner is choosing how.
- Splitting an area across several days is not planned yet; it is the
  owner's call whether it comes next.
- The two-vehicle re-solve and the giant-tour restart (ADR-0003 step 11).
- Truck restrictions from OSM (`hgv=no`, `maxweight`).

**Blocked**

- Merging #29 to #33 needs the owner: the safety check on this machine
  refuses merges.

## 2026-10-26 (phase 4, API and worker)

**Done**

- #36: ADR-0004 covers the tables, org scoping (404 for another org), magic-link
  sign-in, the run lifecycle and the object store. Splitting an area across days
  is post-MVP.
- #37: the `starboard-api` package, the tables, Alembic on PostGIS and `/healthz`.
  CI runs a PostGIS service.
- #38: magic-link sign-in, sessions, organizations, members and roles.
- #39: the stop-file reader moves into geo.
- #40: routes with a truck profile, a yard and a disposal site.
- #41: stop uploads. The `starboard-worker` package and its `import_upload` job
  snap stops; stops needing a planner go to the review list.
- #42: clearing the review queue by placing a stop on a candidate street or
  excluding it.
- #43: runs. The `solve_run` job runs in a process pool, and the report
  (`solver.comparison`) gives current against optimized.
- #44: the Compose stack (PostGIS, Redis 7.2, migrations, API and worker),
  built and started in CI.
- #45: schemathesis on every operation. It found three spec mismatches, all
  fixed.

**Decisions taken as defaults (say if any should change)**

- A stop outside the street network can only be excluded until the map lets
  a planner click any street (phase 5).
- Rule conflicts answer 409, and 422 is kept for validation errors.
- Redis is pinned to 7.2, the last BSD release.

**Next**

- Phase 5: web v1 and deploying to a public URL.
- GitHub and Google OAuth with the sign-in pages.
- A real mail sender and S3-compatible storage for deployment.

**Blocked on the owner**

- The geocoder (HANDOFF §6, item 2). Until then, uploads need lon/lat.
- Fly.io or Railway, and the domain (HANDOFF §6, item 4), before the phase 5
  deploy.
- Docker or Postgres on this machine. Until then, database tests run in CI only.
- Merging #36 to #45.

## 2026-10-26 (phase 5, web v1, running locally)

**Done**

- #47: address uploads are geocoded with the free US Census batch geocoder
  (ADR-0005). Doubtful matches go to review.
- #48: the web app: React, Vite and TanStack Query, with an API client typed
  from the OpenAPI spec (CI checks the two match), sign-in, and organizations.
- #49: routes and stop-list uploads in the web app.
- #50: stops in review carry their point and their candidate streets, drawn,
  each with the curb side its point is on.
- #51: the review queue on a map (MapLibre, OpenFreeMap tiles).
- #52: solving from the route page, and a run page comparing current and
  optimized for the area (the run report is typed in the API).
- #53: `python -m starboard.api.demo you@example.com` preloads the Byram demo.
- #54: the web app runs in Docker Compose, sign-in links are printed in the
  API's output, and an OSM extract can be named in `.env`.
- #55: a stop table on the run page.
- Docker Desktop and WSL2 are installed on the owner's machine; they need a
  restart before they work.

**Decisions (owner, 2026-10-26)**

- A free geocoder for now: US Census (ADR-0005).
- No hosting yet: the product runs locally under Docker Compose. Deploy later.

**Next**

- Tonight, after the restart: `docker compose up --build`, preload the demo,
  sign in, review, and solve (README, "Run it locally"). This is the first run
  of the web app against a real API.
- Phase 6: the route paths from the API, the Current and Optimized map layers,
  playback, permalinks and share links.
- GitHub and Google OAuth. They need client registrations under the owner's
  accounts.

**Blocked on the owner**

- Restarting the PC so Docker works.
- Merging #36 to #55 (say "merge" in the thread).

## 2026-10-26 (phases 6 and 7, comparison view and exports)

**Done**

- #59 to #65 merged: encodings checked in CI, split view, playback, share
  links (API and web), turn-by-turn steps, CSV/GPX/KML exports.
- #66 merged: the printable driver route sheet (PDF), one section per truck.
- #67 merged: exports download from the API, made on request and not stored
  (ADR-0006); org-scoped, with the cross-org test. Not reached by share links.
- #68 merged: download links on the run page.
- #70: route sheet fixes from an independent review: the map on every page,
  long stop ids, the footer, linear path drawing, OpenStreetMap credit.
- #71: control characters (NUL above all) in names and addresses are a 422,
  which ends the random schemathesis 500. A review found more: names now lose
  the spaces around them before their length is checked, the email pattern
  lists its spaces so the spec and the server agree on every character, and a
  stop id path refuses only NUL, so a stop whose id holds a tab can still be
  cleared from review.
- #76: the route sheet embeds DejaVu Sans (ADR-0008), so street names beyond
  Western European letters (Kalākaua, Łódź) print as named. Sheets are laid
  out one at a time, because ReportLab is not safe to subset a font from two
  threads at once.
- The owner approved downloading and committing the DejaVu Sans fonts.
- Docker Desktop and WSL2 work on the owner's machine; API tests now run
  locally against PostGIS (`docker compose up -d db`, database
  `starboard_test`).

**Next**

- A NUL inside an uploaded CSV should become a rejected row, not reach the
  database in the import job.
- OpenStreetMap credit in the GPX and KML files too.
- The first full local run of the web app against the API.

**Blocked on the owner**

- Merging #70, #76 (stacked on #70), #71 and this log (say "merge" in the
  thread).
