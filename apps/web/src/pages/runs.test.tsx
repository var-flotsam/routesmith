import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { vi } from "vitest";

import { fakeApi, ME, renderApp } from "../test-helpers";

// The map needs WebGL, which the test browser lacks; it reports what it was given instead.
vi.mock("../map/RouteMap", () => ({
  RouteMap: (props: {
    current: unknown[];
    optimized: unknown[];
    shown: Set<string>;
    view: string;
    trucks?: { current: unknown[]; optimized: unknown[] };
  }) => (
    <div>
      <p>
        {props.view} map of {props.current.length} current and {props.optimized.length}{" "}
        optimized routes, showing {[...props.shown].sort().join(" and ")}
      </p>
      <p>trucks at {JSON.stringify(props.trucks ?? null)}</p>
    </div>
  ),
}));

const ROUTE = {
  id: "r1",
  name: "Byram",
  yard: { lon: -73.6, lat: 41.0 },
  disposal: { lon: -73.6, lat: 41.0 },
  capacity_carts: 420,
  max_route_hours: null,
};

const READY = {
  id: "up1",
  route_id: "r1",
  file_name: "stops.csv",
  state: "ready",
  rows_read: 4,
  rows_rejected: 0,
  stops_snapped: 4,
  stops_in_review: 0,
  stops_excluded: 0,
  rejected_rows: [],
  osm_snapshot: null,
  failure_reason: null,
  created_at: "2026-10-26T12:00:00Z",
};

const RUN = {
  id: "run1",
  route_id: "r1",
  upload_id: "up1",
  state: "succeeded",
  trucks: 2,
  objective: "balanced-total",
  osm_snapshot: "2026-10-01",
  solver_version: "0.0.0",
  failure_reason: null,
  created_at: "2026-10-26T12:00:00Z",
  started_at: "2026-10-26T12:00:01Z",
  finished_at: "2026-10-26T12:00:30Z",
};

function card(routeTimeS: number, distanceM: number, stops: number) {
  return {
    distance_m: distanceM,
    drive_time_s: routeTimeS / 2,
    service_time_s: routeTimeS / 4,
    wrong_side_time_s: 0,
    unload_time_s: routeTimeS / 4,
    route_time_s: routeTimeS,
    left_turns: 3,
    right_turns: 5,
    u_turns: 0,
    wrong_side_pickups: 0,
    dead_head_m: 100,
    street_passes: 9,
    stops_serviced: stops,
    stops_unreachable: 0,
    disposal_visits: 1,
  };
}

const REPORT = {
  trucks: 2,
  objective: "balanced-total",
  current: {
    routes: [{ route_id: null, scorecard: card(26430, 68288, 4), path: [] }],
    area: card(26430, 68288, 4),
  },
  optimized: {
    routes: [
      {
        scorecard: card(8671, 19733, 2),
        order: ["s1", "s2"],
        path: [
          [1, 0],
          [1, 1],
        ],
      },
      { scorecard: card(7691, 17413, 2), order: ["s3", "s4"], path: [] },
    ],
    area: card(16362, 37146, 4),
  },
  total_route_time_s: 16362,
  longest_route_time_s: 8671,
  total_lower_bound_s: 14174,
  gap: 0.154,
  balance_met: true,
  unserved: [{ stop_id: "s9", reason: "unreachable_from_yard" }],
  time_limited: false,
  osm_snapshot: "2026-10-01",
};

test("a cleared stop list is solved from the route page", async () => {
  const calls = fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/routes/r1": { status: 200, body: ROUTE },
    "GET /orgs/o1/routes/r1/uploads": { status: 200, body: [READY] },
    "GET /orgs/o1/routes/r1/runs": [
      { status: 200, body: [] },
      { status: 200, body: [{ ...RUN, state: "queued" }] },
      { status: 200, body: [RUN] },
    ],
    "POST /orgs/o1/routes/r1/runs": { status: 202, body: { ...RUN, state: "queued" } },
  });
  renderApp("/orgs/o1/routes/r1");
  await userEvent.click(await screen.findByRole("button", { name: "Solve" }));
  expect(await screen.findByRole("link", { name: /2 trucks/ })).toHaveAttribute(
    "href",
    "/orgs/o1/runs/run1",
  );
  await waitFor(() =>
    expect(calls.find((c) => c.key === "POST /orgs/o1/routes/r1/runs")?.body).toEqual({
      upload_id: "up1",
      objective: "balanced-total",
    }),
  );
});

test("a stop list with stops still in review cannot be solved", async () => {
  fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/routes/r1": { status: 200, body: ROUTE },
    "GET /orgs/o1/routes/r1/uploads": { status: 200, body: [{ ...READY, stops_in_review: 2 }] },
    "GET /orgs/o1/routes/r1/runs": { status: 200, body: [] },
  });
  renderApp("/orgs/o1/routes/r1");
  expect(await screen.findByRole("link", { name: "2" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Solve" })).not.toBeInTheDocument();
});

test("a finished run shows current against optimized for the area", async () => {
  fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/runs/run1": { status: 200, body: RUN },
    "GET /orgs/o1/runs/run1/result": { status: 200, body: REPORT },
  });
  renderApp("/orgs/o1/runs/run1");
  const routeTime = (await screen.findByRole("rowheader", { name: "Route time" })).closest("tr");
  expect(routeTime).not.toBeNull();
  const cells = within(routeTime as HTMLElement).getAllByRole("cell");
  expect(cells.map((c) => c.textContent)).toEqual(["7.34 h", "4.54 h", "-2.80 h"]);
  expect(screen.getByText(/at most 15.4% above the lower bound/)).toBeInTheDocument();
  expect(screen.getByText(/s9/)).toBeInTheDocument();
});

test("a failed run says why", async () => {
  fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/runs/run1": {
      status: 200,
      body: { ...RUN, state: "failed", failure_reason: "ConnectionError: no network" },
    },
  });
  renderApp("/orgs/o1/runs/run1");
  expect(await screen.findByText(/The run failed: ConnectionError: no network/)).toBeInTheDocument();
});

test("the stop table lists each stop's current and optimized place, moved most first", async () => {
  const stop = (stopId: string, sequence: number) => ({
    stop_id: stopId,
    lon: -73.6,
    lat: 41.0,
    current_sequence: sequence,
    current_route_id: null,
    street: "Mill St",
    state: "snapped",
    segment_id: "seg",
    curb_side: "right",
    review_reason: null,
    review_detail: null,
    candidate_segment_ids: [],
    candidate_streets: [],
  });
  const oneTruck = {
    ...REPORT,
    trucks: 1,
    optimized: {
      routes: [{ scorecard: card(16362, 37146, 3), order: ["s3", "s1", "s2"], path: [] }],
      area: card(16362, 37146, 3),
    },
  };
  fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/runs/run1": { status: 200, body: { ...RUN, trucks: 1 } },
    "GET /orgs/o1/runs/run1/result": { status: 200, body: oneTruck },
    "GET /orgs/o1/uploads/up1/stops": {
      status: 200,
      body: [stop("s1", 1), stop("s2", 2), stop("s3", 3)],
    },
  });
  renderApp("/orgs/o1/runs/run1");
  const firstColumn = () =>
    screen
      .getAllByRole("row")
      .map((row) => within(row).queryAllByRole("cell")[0]?.textContent)
      .filter((text) => text?.startsWith("s"));
  await screen.findByRole("columnheader", { name: "Optimized order" });
  expect(firstColumn()).toEqual(["s3", "s1", "s2"]);
  await userEvent.click(screen.getByLabelText("Stops that moved most first"));
  expect(firstColumn()[0]).toBe("s3");
});

test("the run map shows both route sets, and each can be hidden", async () => {
  fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/runs/run1": { status: 200, body: RUN },
    "GET /orgs/o1/runs/run1/result": { status: 200, body: REPORT },
    "GET /orgs/o1/uploads/up1/stops": { status: 200, body: [] },
  });
  renderApp("/orgs/o1/runs/run1");
  expect(
    await screen.findByText(/overlay map of 1 current and 2 optimized routes, showing current and optimized/),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox", { name: /Current/ }));
  expect(await screen.findByText(/showing optimized$/)).toBeInTheDocument();
});

test("the routes can be shown side by side", async () => {
  fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/runs/run1": { status: 200, body: RUN },
    "GET /orgs/o1/runs/run1/result": { status: 200, body: REPORT },
    "GET /orgs/o1/uploads/up1/stops": { status: 200, body: [] },
  });
  renderApp("/orgs/o1/runs/run1");
  await userEvent.click(await screen.findByRole("radio", { name: "Side by side" }));
  expect(await screen.findByText(/^split map/)).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: /Current/ })).toBeDisabled();
});

test("playback moves every truck on one clock, and shorter routes finish first", async () => {
  fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/runs/run1": { status: 200, body: RUN },
    "GET /orgs/o1/runs/run1/result": { status: 200, body: REPORT },
    "GET /orgs/o1/uploads/up1/stops": { status: 200, body: [] },
  });
  renderApp("/orgs/o1/runs/run1");
  const slider = await screen.findByRole("slider", { name: "Time into the day" });
  expect(slider).toHaveAttribute("max", "26430");
  fireEvent.change(slider, { target: { value: "8700" } });
  expect(screen.getByText("2:25 into the day")).toBeInTheDocument();
  expect(screen.getByText(/Current: 0 of 1 done. Optimized: 2 of 2 done./)).toBeInTheDocument();
  // The current truck is a third of the way along; the first optimized truck is home.
  expect(screen.getByText(/trucks at/).textContent).toContain('"optimized":[[1,1],null]');
});
