import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import type { Schemas } from "../api/client";
import { ReportView } from "./ReportView";

// As in a browser without WebGL: the map cannot be created.
vi.mock("../map/RouteMap", () => ({
  RouteMap: () => {
    throw new Error("Failed to initialize WebGL");
  },
}));

function card(routeTimeS: number, wrongSide: number): Schemas["ScorecardOut"] {
  return {
    distance_m: 1000,
    drive_time_s: routeTimeS / 2,
    service_time_s: routeTimeS / 4,
    wrong_side_time_s: 0,
    unload_time_s: routeTimeS / 4,
    route_time_s: routeTimeS,
    left_turns: 3,
    right_turns: 5,
    u_turns: 0,
    wrong_side_pickups: wrongSide,
    dead_head_m: 100,
    street_passes: 9,
    stops_serviced: 2,
    stops_unreachable: 0,
    disposal_visits: 1,
  };
}

const REPORT: Schemas["RunReport"] = {
  trucks: 1,
  objective: "balanced-total",
  current: {
    routes: [{ route_id: null, scorecard: card(3600, 1), path: [] }],
    area: card(3600, 1),
  },
  optimized: {
    routes: [{ scorecard: card(1800, 0), order: ["s1", "s2"], path: [], steps: [] }],
    area: card(1800, 0),
  },
  total_route_time_s: 1800,
  longest_route_time_s: 1800,
  total_lower_bound_s: 1500,
  gap: 0.2,
  balance_met: true,
  unserved: [],
  time_limited: false,
  osm_snapshot: null,
};

test("when the map cannot be drawn, the rest of the result still shows", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {}); // React reports the caught error
  render(<ReportView report={REPORT} />);
  expect(await screen.findByText(/This browser cannot draw the map/)).toBeInTheDocument();
  expect(screen.getByRole("rowheader", { name: "Wrong-side pickups" })).toBeInTheDocument();
});
