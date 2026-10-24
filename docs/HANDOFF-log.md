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

- Pushing `main` and opening PRs: waiting on the owner.
- CI needs a `BANNED_TERMS` repository secret holding the term list; the
  owner adds it.
