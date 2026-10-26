import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useState } from "react";
import { Link, useParams } from "react-router";

import { api, dataOf, type Schemas } from "../api/client";
import { CURRENT_COLOUR, truckColour } from "../map/style";
import type { Layer } from "../map/RouteMap";
import { StopTable } from "./StopTable";

// The map library is large and needs WebGL, so it loads only when a map is shown.
const RouteMap = lazy(async () => ({ default: (await import("../map/RouteMap")).RouteMap }));

function Swatch({ colour }: { colour: string }) {
  return <span className="swatch" style={{ background: colour }} />;
}

type Scorecard = Schemas["ScorecardOut"];

// How often a run that is still solving is checked again.
const RUNNING_POLL_MS = 3000;

const SECONDS_PER_HOUR = 3600;
const METRES_PER_KM = 1000;

// The scorecard rows, in the order a planner reads them; every number is the API's.
const ROWS: { label: string; key: keyof Scorecard; unit: "h" | "km" | "count" }[] = [
  { label: "Route time", key: "route_time_s", unit: "h" },
  { label: "Driving", key: "drive_time_s", unit: "h" },
  { label: "Collecting carts", key: "service_time_s", unit: "h" },
  { label: "Wrong-side extra", key: "wrong_side_time_s", unit: "h" },
  { label: "Unloading", key: "unload_time_s", unit: "h" },
  { label: "Distance", key: "distance_m", unit: "km" },
  { label: "Dead-head distance", key: "dead_head_m", unit: "km" },
  { label: "Left turns", key: "left_turns", unit: "count" },
  { label: "Right turns", key: "right_turns", unit: "count" },
  { label: "U-turns", key: "u_turns", unit: "count" },
  { label: "Wrong-side pickups", key: "wrong_side_pickups", unit: "count" },
  { label: "Street passes", key: "street_passes", unit: "count" },
  { label: "Disposal visits", key: "disposal_visits", unit: "count" },
  { label: "Stops serviced", key: "stops_serviced", unit: "count" },
];

function shown(value: number, unit: "h" | "km" | "count"): string {
  if (unit === "h") return `${(value / SECONDS_PER_HOUR).toFixed(2)} h`;
  if (unit === "km") return `${(value / METRES_PER_KM).toFixed(1)} km`;
  return value.toLocaleString("en-US");
}

function change(current: number, optimized: number, unit: "h" | "km" | "count"): string {
  const delta = optimized - current;
  return `${delta > 0 ? "+" : ""}${shown(delta, unit)}`;
}

function Comparison({ current, optimized }: { current: Scorecard; optimized: Scorecard }) {
  return (
    <table>
      <thead>
        <tr>
          <th />
          <th>Current</th>
          <th>Optimized</th>
          <th>Change</th>
        </tr>
      </thead>
      <tbody>
        {ROWS.map(({ label, key, unit }) => (
          <tr key={key}>
            <th scope="row">{label}</th>
            <td>{shown(current[key], unit)}</td>
            <td>{shown(optimized[key], unit)}</td>
            <td>{change(current[key], optimized[key], unit)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** One run: its state while solving, then current against optimized for the area. */
export function RunPage() {
  const { orgId = "", runId = "" } = useParams();
  const path = { org_id: orgId, run_id: runId };
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: async () => dataOf(await api.GET("/orgs/{org_id}/runs/{run_id}", { params: { path } })),
    refetchInterval: (query) =>
      query.state.data?.state === "queued" || query.state.data?.state === "running"
        ? RUNNING_POLL_MS
        : false,
  });
  const succeeded = run.data?.state === "succeeded";
  const [layers, setLayers] = useState<Set<Layer>>(new Set(["current", "optimized"]));
  function toggle(layer: Layer) {
    const next = new Set(layers);
    if (next.has(layer)) next.delete(layer);
    else next.add(layer);
    setLayers(next);
  }
  const report = useQuery({
    queryKey: ["result", runId],
    enabled: succeeded,
    queryFn: async () =>
      dataOf(await api.GET("/orgs/{org_id}/runs/{run_id}/result", { params: { path } })),
  });

  return (
    <section>
      {run.data && (
        <p>
          <Link to={`/orgs/${orgId}/routes/${run.data.route_id}`}>Back to the route</Link>
        </p>
      )}
      <h1>Run</h1>
      {run.isError && <p className="error">{run.error.message}</p>}
      {run.data && !succeeded && (
        <p>
          {run.data.state === "failed"
            ? `The run failed: ${run.data.failure_reason ?? "no reason given"}`
            : `Solving for ${run.data.trucks} trucks (${run.data.state})â€¦`}
        </p>
      )}
      {report.isError && <p className="error">{report.error.message}</p>}
      {report.data && (
        <>
          <p>
            {report.data.trucks} {report.data.trucks === 1 ? "truck" : "trucks"}. Best found:
            at most {(report.data.gap * 100).toFixed(1)}% above the lower bound.{" "}
            {report.data.balance_met
              ? "Every route is within the balance margin."
              : "The routes are not all within the balance margin."}
          </p>
          {report.data.time_limited && (
            <p className="muted">The search hit its time ceiling; another machine may differ.</p>
          )}
          <div className="layers" role="group" aria-label="Map layers">
            <label className="inline">
              <input
                type="checkbox"
                checked={layers.has("current")}
                onChange={() => toggle("current")}
              />
              <Swatch colour={CURRENT_COLOUR} /> Current
            </label>
            <label className="inline">
              <input
                type="checkbox"
                checked={layers.has("optimized")}
                onChange={() => toggle("optimized")}
              />
              {report.data.optimized.routes.map((_, index) => (
                <Swatch key={index} colour={truckColour(index)} />
              ))}{" "}
              Optimized
            </label>
          </div>
          <Suspense fallback={<div className="map large">Loading the map…</div>}>
            <RouteMap
              current={report.data.current.routes.map((r) => r.path)}
              optimized={report.data.optimized.routes.map((r) => r.path)}
              shown={layers}
            />
          </Suspense>
          <h2>The whole area</h2>
          <Comparison current={report.data.current.area} optimized={report.data.optimized.area} />
          <h2>Optimized routes</h2>
          <table>
            <thead>
              <tr>
                <th>Route</th>
                <th />
                <th>Route time</th>
                <th>Distance</th>
                <th>Stops</th>
              </tr>
            </thead>
            <tbody>
              {report.data.optimized.routes.map((route, index) => (
                <tr key={index}>
                  <th scope="row">{index + 1}</th>
                  <td>
                    <Swatch colour={truckColour(index)} />
                  </td>
                  <td>{shown(route.scorecard.route_time_s, "h")}</td>
                  <td>{shown(route.scorecard.distance_m, "km")}</td>
                  <td>{route.scorecard.stops_serviced}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {run.data && (
            <>
              <h2>Stops</h2>
              <StopTable orgId={orgId} uploadId={run.data.upload_id} report={report.data} />
            </>
          )}
          {report.data.unserved.length > 0 && (
            <>
              <h2>Stops no route can serve</h2>
              <ul>
                {report.data.unserved.map((u) => (
                  <li key={u.stop_id}>
                    {u.stop_id} <span className="muted">({u.reason.replaceAll("_", " ")})</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
