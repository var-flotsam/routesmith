import { lazy, Suspense, useCallback, useState, type ReactNode } from "react";

import type { Schemas } from "../api/client";
import type { Layer, Trucks, View } from "../map/RouteMap";
import { CURRENT_COLOUR, truckColour } from "../map/style";
import { Playback } from "./Playback";

// The map library is large and needs WebGL, so it loads only when a map is shown.
const RouteMap = lazy(async () => ({ default: (await import("../map/RouteMap")).RouteMap }));

function Swatch({ colour }: { colour: string }) {
  return <span className="swatch" style={{ background: colour }} />;
}

type Scorecard = Schemas["ScorecardOut"];

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

/** A run's result: the map with playback, the area's scorecards, each optimized route,
 * and stops no route can serve. `children` go after the route table. */
export function ReportView({
  report,
  children,
}: {
  report: Schemas["RunReport"];
  children?: ReactNode;
}) {
  const [layers, setLayers] = useState<Set<Layer>>(new Set(["current", "optimized"]));
  const [view, setView] = useState<View>("overlay");
  const [trucks, setTrucks] = useState<Trucks>({ current: [], optimized: [] });
  const onTrucks = useCallback((next: Trucks) => setTrucks(next), []);
  function toggle(layer: Layer) {
    const next = new Set(layers);
    if (next.has(layer)) next.delete(layer);
    else next.add(layer);
    setLayers(next);
  }
  return (
    <>
          <p>
            {report.trucks} {report.trucks === 1 ? "truck" : "trucks"}. Best found:
            at most {(report.gap * 100).toFixed(1)}% above the lower bound.{" "}
            {report.balance_met
              ? "Every route is within the balance margin."
              : "The routes are not all within the balance margin."}
          </p>
          {report.time_limited && (
            <p className="muted">The search hit its time ceiling; another machine may differ.</p>
          )}
          <div className="layers" role="group" aria-label="Map view">
            <label className="inline">
              <input
                type="radio"
                name="view"
                checked={view === "overlay"}
                onChange={() => setView("overlay")}
              />
              One map
            </label>
            <label className="inline">
              <input
                type="radio"
                name="view"
                checked={view === "split"}
                onChange={() => setView("split")}
              />
              Side by side
            </label>
          </div>
          <div className="layers" role="group" aria-label="Map layers">
            <label className="inline">
              <input
                type="checkbox"
                disabled={view === "split"}
                checked={layers.has("current")}
                onChange={() => toggle("current")}
              />
              <Swatch colour={CURRENT_COLOUR} /> Current
            </label>
            <label className="inline">
              <input
                type="checkbox"
                disabled={view === "split"}
                checked={layers.has("optimized")}
                onChange={() => toggle("optimized")}
              />
              {report.optimized.routes.map((_, index) => (
                <Swatch key={index} colour={truckColour(index)} />
              ))}{" "}
              Optimized
            </label>
          </div>
          <Suspense fallback={<div className="map large">Loading the map…</div>}>
            <RouteMap
              current={report.current.routes.map((r) => r.path)}
              optimized={report.optimized.routes.map((r) => r.path)}
              shown={layers}
              view={view}
              trucks={trucks}
            />
          </Suspense>
          <Playback report={report} onTrucks={onTrucks} />
          <h2>The whole area</h2>
          <Comparison current={report.current.area} optimized={report.optimized.area} />
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
              {report.optimized.routes.map((route, index) => (
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
          {children}
          {report.unserved.length > 0 && (
            <>
              <h2>Stops no route can serve</h2>
              <ul>
                {report.unserved.map((u) => (
                  <li key={u.stop_id}>
                    {u.stop_id} <span className="muted">({u.reason.replaceAll("_", " ")})</span>
                  </li>
                ))}
              </ul>
            </>
          )}
    </>
  );
}
