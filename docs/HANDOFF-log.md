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
