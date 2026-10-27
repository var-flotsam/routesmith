# ADR-0007: A static public demo of the demo route's result

Date: 2026-10-26

## Context

On 2026-10-26 the owner decided the product runs locally under Docker Compose and
is not deployed for now (HANDOFF §4, phase 5). The same day the owner asked for a
public demo that anyone can open: free, no keys, no paid hosting, and nothing that
needs a running backend. The product's result page needs the API, a database, a
worker and a signed-in user, so it cannot be that demo as it is. A share link's
page (`/shared/{token}`) already shows one run's result read-only, without sign-in;
everything on it comes from one API answer, `SharedRun`.

## Decision

- `starboard.worker.demo_result` builds the result a run gives for an upload of
  `data/demo/stops.csv` on the demo route, once a planner has left out every stop
  in review (the product does not solve while any stop is in review). It snaps the
  stops as the import job does, then solves the snapped ones with the worker's own
  `solve_report` and the number of trucks the API gives a run by default. It writes
  the answer a share link would give (`SharedRun`) to
  `data/demo/result/shared-run.json`, and `data/demo/result/about.json` with what
  the result was built from: the place, how the current route is driven, how many
  stops were placed and how many go to review, the OSM snapshot, and the SHA-256
  of `stops.csv` and `route.json`. The files are committed. A test checks they
  read back as the API's models, match the committed input files, and are written
  exactly as the builder writes them; a `demo`-marked test rebuilds them from the
  cached network and compares.
- The web app gains a demo build (`pnpm build:demo`, Vite mode `demo`). It shows
  only the demo page: the shared-result view filled from those two files, with a
  note saying what the product does and that the result is precomputed. It has no
  sign-in, no forms and no API calls. Its data still goes through TanStack Query.
  Every scorecard number comes from the `RunReport` in `shared-run.json` and the
  stop counts from `about.json`; the page computes only differences and the review
  total, as the run page does.
- `.github/workflows/pages.yml` publishes the demo build to GitHub Pages from
  `main`, but only once the repository variable `PAGES_ENABLED` is `true`. On the
  free plan, Pages needs a public repository, and making the repository public is
  the owner's decision. After setting the variable, run the workflow once from the
  Actions tab, since setting a variable starts nothing. The workflow skips other
  branches, but the guarantee that only `main` deploys is the `github-pages`
  environment's deployment-branch rule, which should stay set to `main`. CI builds
  the demo on every pull request.
- The result's paths and street names are derived from OpenStreetMap, so the files
  in `data/demo/result/` are under the ODbL 1.0, as `data/demo/result/LICENSE.md`
  says; everything else stays under FSL-1.1-ALv2 (ADR-0001).
- The product itself stays undeployed. This ADR changes the 2026-10-26 decision
  only for this static page.

The builder and the committed result land first; the web build, the workflow and
the CI step follow in the next pull requests.

## Consequences

- The demo costs nothing to host, and nothing is solved in a visitor's browser.
  The page says so, and says the current route is synthetic and how it is driven.
- The result goes stale when the demo files, the solver or the scorecard change.
  A change to `stops.csv` or `route.json`, or to `RunReport`, fails the
  committed-result test in CI. A solver or scorecard change shows up in
  `pytest -m demo` on a machine whose cached network is the committed snapshot.
  Regenerate with `uv run python -m starboard.worker.demo_result --osm-extract
  <extract>` on a machine that has the Connecticut extract or can reach Overpass;
  an unchanged result is rewritten byte for byte.
- The demo page credits OpenStreetMap and links to its copyright page.
- The stops that go to review are left out of both routes, as if a planner had
  excluded them; in the product a planner places or excludes each one before a
  run. The page gives their count and reasons.
- The Pages base path is the repository name. A custom domain would need the base
  from `actions/configure-pages` instead.
