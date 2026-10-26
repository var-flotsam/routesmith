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
