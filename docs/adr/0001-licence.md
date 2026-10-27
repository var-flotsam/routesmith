# ADR-0001: Licence is FSL-1.1-ALv2

Date: 2026-10-24 (recorded 2026-10-25)

## Context

The product is sold as a hosted service. The source should be readable by
customers and contributors without allowing a competitor to run it as a
competing service.

## Decision

The repository is licensed under the Functional Source License 1.1 with the
Apache 2.0 future licence (FSL-1.1-ALv2), as `LICENSE.md` states, except the
folders named under Consequences, which keep their own licences.
Each version becomes available under Apache 2.0 two years after it is made
available. The copyright holder is "var-flotsam".

## Consequences

- Source-available, not open source, for two years per version.
- Dependencies must be compatible: GPL and AGPL libraries are not linked into
  the product. Services run alongside it over a network (such as a
  self-hosted Nominatim) are not dependencies in this sense.
- The route sheet's fonts, in `packages/export/src/starboard/export/fonts/`,
  are not under it: they are DejaVu Sans, unmodified, under the Bitstream Vera
  and Arev font licences in that folder's `LICENSE` (ADR-0008, 2026-10-26).
