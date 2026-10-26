# apps/worker

arq worker running the `import_upload` and `solve_run` jobs. Built in phase 4.

`python -m starboard.worker.demo_result` builds the static demo's result as these jobs
would for an upload of the demo stops, with the stops in review left out (see
`data/demo/PROVENANCE.md` and `docs/adr/0007-static-demo.md`).
