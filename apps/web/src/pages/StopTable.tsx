import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, dataOf, type Schemas } from "../api/client";

type Row = {
  stopId: string;
  street: string | null;
  currentRoute: string | null;
  currentSequence: number;
  optimizedRoute: number;
  optimizedSequence: number;
};

/** How many places a stop moved in a single route. */
function moved(row: Row): number {
  return Math.abs(row.optimizedSequence - row.currentSequence);
}

/** Every served stop: where it is in today's order and where it is in the optimized one. */
export function StopTable({
  orgId,
  uploadId,
  report,
}: {
  orgId: string;
  uploadId: string;
  report: Schemas["RunReport"];
}) {
  const [movedFirst, setMovedFirst] = useState(false);
  const stops = useQuery({
    queryKey: ["stops", uploadId],
    queryFn: async () =>
      dataOf(
        await api.GET("/orgs/{org_id}/uploads/{upload_id}/stops", {
          params: { path: { org_id: orgId, upload_id: uploadId } },
        }),
      ),
  });
  if (stops.isError) return <p className="error">{stops.error.message}</p>;
  if (stops.data === undefined) return <p>Loading the stops…</p>;

  const byId = new Map(stops.data.map((s) => [s.stop_id, s]));
  const rows: Row[] = report.optimized.routes.flatMap((route, routeIndex) =>
    route.order.map((stopId, position) => {
      const stop = byId.get(stopId);
      return {
        stopId,
        street: stop?.street ?? null,
        currentRoute: stop?.current_route_id ?? null,
        currentSequence: stop?.current_sequence ?? 0,
        optimizedRoute: routeIndex + 1,
        optimizedSequence: position + 1,
      };
    }),
  );
  const sameRoutes = report.optimized.routes.length === 1 && report.current.routes.length === 1;
  // Places in different routes cannot be compared, so the ordering applies to one route only.
  const shown = movedFirst && sameRoutes ? [...rows].sort((a, b) => moved(b) - moved(a)) : rows;

  return (
    <>
      {sameRoutes && (
      <label className="inline">
        <input
          type="checkbox"
          checked={movedFirst}
          onChange={(event) => setMovedFirst(event.target.checked)}
        />
        Stops that moved most first
      </label>
      )}
      <table>
        <thead>
          <tr>
            <th>Stop</th>
            <th>Street</th>
            <th>Current route</th>
            <th>Current order</th>
            <th>Optimized route</th>
            <th>Optimized order</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr key={row.stopId}>
              <td>{row.stopId}</td>
              <td>{row.street}</td>
              <td>{row.currentRoute ?? "—"}</td>
              <td>{row.currentSequence}</td>
              <td>{row.optimizedRoute}</td>
              <td>{row.optimizedSequence}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
