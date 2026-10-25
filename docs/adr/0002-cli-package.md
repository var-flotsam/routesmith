# ADR-0002: The `starboard` CLI lives in `apps/cli`

Date: 2026-10-25

## Context

`starboard score` and `starboard optimize` read a stop file, fetch the OSM
network, snap stops and run the solver. The solver must stay pure (no I/O),
and geo is the only place OSM is touched, so neither package can own a
command that does both.

## Decision

The command line is its own workspace package, `starboard-cli` in
`apps/cli`, with the `starboard` entry point. It depends on `starboard-geo`
and `starboard-solver` and holds only argument parsing, stop-file reading
and output formatting. It sits beside the API and worker because, like
them, it is an entry point that wires the packages together.

## Consequences

- The solver and geo packages keep their boundaries; the CLI can grow
  `optimize` without either changing.
- The stop-file reader here covers the demo layout only. The interactive
  column mapping in the web importer (phase 5) is a separate module that the
  CLI can adopt later.
