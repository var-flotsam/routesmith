import type { Schemas } from "../api/client";

// Each file the API makes from a run, named as a dispatcher would look for it.
const FILES: { file: Schemas["ExportFile"]; label: string }[] = [
  { file: "route-sheet.pdf", label: "Driver route sheets (PDF)" },
  { file: "stops.csv", label: "Stops in the new order (CSV)" },
  { file: "routes.gpx", label: "Route paths for GPS units (GPX)" },
  { file: "routes.kml", label: "Route paths for Google Earth (KML)" },
];

/** Links to the run's exports; the browser saves each under the name the API gives it. */
export function Downloads({ orgId, runId }: { orgId: string; runId: string }) {
  const exports = `${window.location.origin}/api/orgs/${orgId}/runs/${runId}/exports`;
  return (
    <div className="downloads">
      <h2>Downloads</h2>
      <p className="muted">The route sheet has a section for each truck, to print for its driver.</p>
      <ul>
        {FILES.map(({ file, label }) => (
          <li key={file}>
            <a href={`${exports}/${file}`} download>
              {label}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
