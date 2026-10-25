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
