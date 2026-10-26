# ADR-0001: Licence is FSL-1.1-ALv2

Date: 2026-10-24 (recorded 2026-10-25)

## Context

The product is sold as a hosted service. The source should be readable by
customers and contributors without allowing a competitor to run it as a
competing service.

## Decision

The whole repository is licensed under the Functional Source License 1.1
with the Apache 2.0 future licence (FSL-1.1-ALv2), as `LICENSE.md` states.
Each version becomes available under Apache 2.0 two years after it is made
available. The copyright holder is "var-flotsam".

## Consequences

- Source-available, not open source, for two years per version.
- One folder is not under it: `data/demo/result/`, the static demo's result,
  is derived from OpenStreetMap and is under the ODbL 1.0 (ADR-0007, 2026-10-26).
- Dependencies must be compatible: GPL and AGPL libraries are not linked into
  the product. Services run alongside it over a network (such as a
  self-hosted Nominatim) are not dependencies in this sense.
