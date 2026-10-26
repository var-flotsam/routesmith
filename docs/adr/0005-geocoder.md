# ADR-0005: A free geocoder for now: the US Census batch geocoder

Date: 2026-10-26

## Context

Uploads may give stops by address rather than lon/lat (HANDOFF §2.1). HANDOFF §6
item 2 leaves the geocoder to the owner. On 2026-10-26 the owner chose a free
geocoder for the time being. The candidates were the public Nominatim service
and the US Census Bureau's geocoder. Nominatim's usage policy allows one request
per second, which means about 17 minutes for a 1,000-stop upload, and it
discourages bulk geocoding. The Census geocoder takes up to 10,000 addresses in
one batch request, needs no key, and covers the United States
(https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html).

## Decision

`starboard.geo.geocoding` defines a `Geocoder` interface and `CensusGeocoder`,
which sends one batch per 10,000 addresses against the current address ranges
(`Public_AR_Current`) and caches every answer under `cache/geocode/`. Answers map
to four qualities: exact, inexact (matched after the geocoder changed the
address), ambiguous, and not found. The import job geocodes every address-only
stop in one call. Exact matches are snapped like any other stop; inexact matches
go to review with the street they snapped to as the one candidate; ambiguous and
not-found addresses go to review with no location, so they can only be excluded
until the map lets a planner place them.

## Consequences

- Address uploads cost nothing and need no account; a re-upload asks only for
  addresses not already cached.
- Only US addresses can be geocoded. A paid or self-hosted geocoder can replace
  it behind the same interface when the owner decides.
- Geocoder answers stay in `cache/`, which git ignores (CLAUDE.md, data rules).
