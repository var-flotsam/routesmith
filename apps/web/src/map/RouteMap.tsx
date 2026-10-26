import type { FeatureCollection } from "geojson";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";

import { BASEMAP_STYLE, CURRENT_COLOUR, truckColour } from "./style";

export type Layer = "current" | "optimized";

// Room around the routes when the map first fits them.
const FIT_PADDING_PX = 40;

type Path = [number, number][];

function lines(paths: Path[], colours: (index: number) => string): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: paths.map((path, index) => ({
      type: "Feature",
      properties: { colour: colours(index) },
      geometry: { type: "LineString", coordinates: path },
    })),
  };
}

/** Current and optimized routes on one map; `shown` picks which layers are visible. */
export function RouteMap({
  current,
  optimized,
  shown,
}: {
  current: Path[];
  optimized: Path[];
  shown: Set<Layer>;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (container.current === null) return;
    const created = new maplibregl.Map({ container: container.current, style: BASEMAP_STYLE });
    created.on("load", () => {
      const add = (id: Layer, data: FeatureCollection, width: number) => {
        created.addSource(id, { type: "geojson", data });
        created.addLayer({
          id,
          type: "line",
          source: id,
          layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-color": ["get", "colour"], "line-width": width, "line-opacity": 0.8 },
        });
      };
      add("current", lines(current, () => CURRENT_COLOUR), 6);
      add("optimized", lines(optimized, truckColour), 3);
      const bounds = new maplibregl.LngLatBounds();
      for (const path of [...current, ...optimized]) for (const point of path) bounds.extend(point);
      if (!bounds.isEmpty()) created.fitBounds(bounds, { padding: FIT_PADDING_PX, animate: false });
    });
    map.current = created;
    return () => {
      created.remove();
      map.current = null;
    };
    // One run's routes do not change; visibility is updated below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const current = map.current;
    if (current === null) return;
    const apply = () => {
      for (const layer of ["current", "optimized"] as const) {
        if (current.getLayer(layer)) {
          current.setLayoutProperty(layer, "visibility", shown.has(layer) ? "visible" : "none");
        }
      }
    };
    if (current.isStyleLoaded()) apply();
    else current.once("load", apply);
  }, [shown]);

  return <div ref={container} className="map large" aria-label="Map of current and optimized routes" />;
}
