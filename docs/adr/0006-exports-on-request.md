# ADR-0006: Exports are made on request, not stored

Date: 2026-10-26

## Context

A run's exports are the driver route sheet (PDF), the stops in the new order
(CSV), and each route's path (GPX and KML) (HANDOFF §2.1, step 6). HANDOFF §3
lists S3-compatible object storage for "uploads and PDF exports". The exports
are deterministic: the same run gives byte-identical files (CLAUDE.md), and
everything they are made from is already stored, in the run's result and its
upload's stops. Laying out a route sheet for a 1,000-stop route takes well under
a second.

## Decision

`GET /orgs/{org_id}/runs/{run_id}/exports/{file}` makes the file when it is asked
for, from the stored result and stops, and returns it as an attachment. Nothing
is written to object storage. The PDF is laid out in a worker thread, so a long
route sheet does not hold up other requests. Any member of the run's
organization, viewers included, can download; a share link does not reach the
exports, because they carry stop locations the shared result does not show.

## Consequences

- There is no export file to keep in step with its run, to clean up, or to
  delete with an organization: deleting the run's rows deletes its exports.
- Every download costs the time to make the file again. If that grows (much
  larger routes, many downloads), the bytes can be cached by run and file, since
  they never change.
- A change to an export's layout changes the file a past run gives. The
  snapshot tests in `packages/export` make every such change deliberate.
- Object storage is used for uploads only.
