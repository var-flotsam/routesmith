import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { fakeApi, ME, renderApp } from "../test-helpers";

// The map needs WebGL, which the test browser lacks; the page around it is what is tested.
vi.mock("../map/ReviewMap", () => ({
  ReviewMap: ({ stop }: { stop: { stop_id: string } }) => <div>map of {stop.stop_id}</div>,
}));

const UPLOAD = {
  id: "up1",
  route_id: "r1",
  file_name: "stops.csv",
  state: "ready",
  rows_read: 3,
  rows_rejected: 0,
  stops_snapped: 1,
  stops_in_review: 2,
  stops_excluded: 0,
  rejected_rows: [],
  osm_snapshot: null,
  failure_reason: null,
  created_at: "2026-10-26T12:00:00Z",
};

function stop(stopId: string, reason: string, streets: { id: string; name: string }[]) {
  return {
    stop_id: stopId,
    lon: -73.65,
    lat: 41.0,
    current_sequence: 1,
    current_route_id: null,
    street: null,
    state: "review",
    segment_id: null,
    curb_side: null,
    review_reason: reason,
    review_detail: null,
    candidate_segment_ids: streets.map((s) => s.id),
    candidate_streets: streets.map((s) => ({
      segment_id: s.id,
      name: s.name,
      curb_side: "left",
      line: [
        [-73.651, 41.0],
        [-73.649, 41.0],
      ],
    })),
  };
}

const CORNER = stop("s7", "ambiguous_street", [
  { id: "seg-a", name: "Mill St" },
  { id: "seg-b", name: "Byram Rd" },
]);
const NOWHERE = stop("s9", "address_not_found", []);

test("a planner puts a corner lot on the street they pick, on the curb its point is on", async () => {
  const calls = fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/uploads/up1": { status: 200, body: UPLOAD },
    "GET /orgs/o1/uploads/up1/stops": [
      { status: 200, body: [CORNER, NOWHERE] },
      { status: 200, body: [NOWHERE] },
    ],
    "PUT /orgs/o1/uploads/up1/stops/s7/placement": { status: 200, body: CORNER },
  });
  renderApp("/orgs/o1/uploads/up1/review");
  expect(await screen.findByRole("heading", { name: "Stop s7" })).toBeInTheDocument();
  expect(await screen.findByText("map of s7")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Collect from Byram Rd" }));
  await waitFor(() => expect(screen.getByRole("heading", { name: "Stop s9" })).toBeInTheDocument());
  expect(calls.find((c) => c.key.endsWith("/placement"))?.body).toEqual({
    segment_id: "seg-b",
    curb_side: "left",
  });
});

test("the far curb can be chosen when the cart stands across the street", async () => {
  const calls = fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/uploads/up1": { status: 200, body: UPLOAD },
    "GET /orgs/o1/uploads/up1/stops": { status: 200, body: [CORNER] },
    "PUT /orgs/o1/uploads/up1/stops/s7/placement": { status: 200, body: CORNER },
  });
  renderApp("/orgs/o1/uploads/up1/review");
  await userEvent.click(await screen.findByRole("button", { name: "the cart is across Mill St" }));
  await waitFor(() =>
    expect(calls.find((c) => c.key.endsWith("/placement"))?.body).toEqual({
      segment_id: "seg-a",
      curb_side: "right",
    }),
  );
});

test("an address that cannot be placed can only be left out", async () => {
  const calls = fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/uploads/up1": { status: 200, body: UPLOAD },
    "GET /orgs/o1/uploads/up1/stops": [
      { status: 200, body: [NOWHERE] },
      { status: 200, body: [] },
    ],
    "PUT /orgs/o1/uploads/up1/stops/s9/exclusion": { status: 200, body: NOWHERE },
  });
  renderApp("/orgs/o1/uploads/up1/review");
  expect(await screen.findByText(/no street to choose/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Leave this stop out" }));
  expect(await screen.findByText(/Nothing left to review/)).toBeInTheDocument();
  expect(calls.some((c) => c.key === "PUT /orgs/o1/uploads/up1/stops/s9/exclusion")).toBe(true);
  expect(screen.getByRole("link", { name: "Back to the route" })).toHaveAttribute(
    "href",
    "/orgs/o1/routes/r1",
  );
});
