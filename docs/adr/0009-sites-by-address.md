# ADR-0009: A route's sites are found by address while the planner waits

Date: 2026-10-27

## Context

A route has a yard and a disposal site (HANDOFF §2.1, step 2: "Address or
lat/lon for each location"). The route form took longitude and latitude only,
which a planner has to look up elsewhere and can easily get in the wrong order.
Stop addresses are geocoded in the worker, in one batch per upload (ADR-0005),
but a route's two sites are set while the planner is at the form, and an
address can fit more than one place.

## Decision

`GET /orgs/{org_id}/places?address=...` answers, during the request, with every
place the address could be, best first, from the US Census one-line search
(`CensusGeocoder.find`, cached under `cache/geocode/` like the batch answers).
Text that reads as "lat, lon" is taken as that point instead, for a site with no
street address the geocoder knows. Only a planner or owner of the organization
can ask, so the endpoint is not an open geocoding service. When the service
does not answer, the request is a 502, not a server error.

The web form looks each site up when its field is left, shows the address it
was matched as, and asks the planner to pick when several places fit. The route
keeps each site's point and the address it was matched as (`yard_address`,
`disposal_address`; none for a point given as lat, lon), and the route page
shows them.

## Consequences

- A planner types addresses; nothing on the form asks for coordinates.
- The API now calls out to the geocoder during a request. A slow or absent
  Census service delays or fails the lookup (the form says so), never a stored
  route.
- The geocoder covers the United States only, as for stops (ADR-0005), and its
  one-line search takes at most 100 characters; the API and the form refuse a
  longer address rather than send it.
- Answers are cached whole or not at all (written to a temporary file, then
  renamed), so two lookups of one address at once, or a write cut short, never
  leave a half answer to read.
- Routes made before this keep their points and show them as coordinates until
  a site is set again.
