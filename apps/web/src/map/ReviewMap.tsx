import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";

import type { FeatureCollection } from "geojson";

import type { Schemas } from "../api/client";

// Free vector tiles from OpenStreetMap data, no key needed (https://openfreemap.org).
export const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";
// Close enough to read street names around one stop.
const STOP_ZOOM = 17;

type Stop = Schemas["StopOut"];

function candidateLines(stop: Stop, chosen: string | null): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: stop.candidate_streets.map((street) => ({
      type: "Feature",
      properties: { chosen: street.segment_id === chosen },
      geometry: { type: "LineString", coordinates: street.line },
    })),
  };
}

/** One stop in review: its point, and the streets it could be on (the chosen one bold). */
export function ReviewMap({ stop, chosen }: { stop: Stop; chosen: string | null }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const marker = useRef<maplibregl.Marker | null>(null);

  useEffect(() => {
    if (container.current === null) return;
    const created = new maplibregl.Map({ container: container.current, style: BASEMAP_STYLE });
    created.on("load", () => {
      created.addSource("candidates", { type: "geojson", data: candidateLines(stop, chosen) });
      created.addLayer({
        id: "candidates",
        type: "line",
        source: "candidates",
        paint: {
          "line-color": ["case", ["get", "chosen"], "#2563eb", "#f59e0b"],
          "line-width": ["case", ["get", "chosen"], 8, 5],
          "line-opacity": 0.85,
        },
      });
    });
    map.current = created;
    return () => {
      created.remove();
      map.current = null;
    };
    // The map is built once; later stops and choices update it below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const current = map.current;
    if (current === null || stop.lon === null || stop.lat === null) return;
    const point: [number, number] = [stop.lon, stop.lat];
    current.jumpTo({ center: point, zoom: STOP_ZOOM });
    marker.current?.remove();
    marker.current = new maplibregl.Marker().setLngLat(point).addTo(current);
    const source = current.getSource("candidates") as maplibregl.GeoJSONSource | undefined;
    source?.setData(candidateLines(stop, chosen));
  }, [stop, chosen]);

  return <div ref={container} className="map" aria-label="Map of the stop and its streets" />;
}
