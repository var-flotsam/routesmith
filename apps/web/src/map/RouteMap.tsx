import type { FeatureCollection } from "geojson";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";

import { BASEMAP_STYLE, CURRENT_COLOUR, truckColour } from "./style";

export type Layer = "current" | "optimized";

/** One map with both layers, or two side by side (current left) that move together. */
export type View = "overlay" | "split";

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

/** A map fitted to all the routes, drawing the given layers. */
function routeMap(
  container: HTMLDivElement,
  layers: Layer[],
  current: Path[],
  optimized: Path[],
): maplibregl.Map {
  const map = new maplibregl.Map({ container, style: BASEMAP_STYLE });
  const bounds = new maplibregl.LngLatBounds();
  for (const path of [...current, ...optimized]) for (const point of path) bounds.extend(point);
  if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: FIT_PADDING_PX, animate: false });
  map.on("load", () => {
    const add = (id: Layer, data: FeatureCollection, width: number) => {
      map.addSource(id, { type: "geojson", data });
      map.addLayer({
        id,
        type: "line",
        source: id,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": ["get", "colour"], "line-width": width, "line-opacity": 0.8 },
      });
    };
    if (layers.includes("current")) add("current", lines(current, () => CURRENT_COLOUR), 6);
    if (layers.includes("optimized")) add("optimized", lines(optimized, truckColour), 3);
  });
  return map;
}

/** Keep two maps on the same view: whichever the planner moves, the other follows. */
function moveTogether(a: maplibregl.Map, b: maplibregl.Map): void {
  let following = false;
  const follow = (from: maplibregl.Map, to: maplibregl.Map) => () => {
    if (following) return;
    following = true;
    to.jumpTo({
      center: from.getCenter(),
      zoom: from.getZoom(),
      bearing: from.getBearing(),
      pitch: from.getPitch(),
    });
    following = false;
  };
  a.on("move", follow(a, b));
  b.on("move", follow(b, a));
}

/** Current and optimized routes; `shown` picks the visible layers on the overlay view. */
export function RouteMap({
  current,
  optimized,
  shown,
  view,
}: {
  current: Path[];
  optimized: Path[];
  shown: Set<Layer>;
  view: View;
}) {
  const left = useRef<HTMLDivElement>(null);
  const right = useRef<HTMLDivElement>(null);
  const overlay = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (left.current === null) return;
    const maps: maplibregl.Map[] = [];
    if (view === "split" && right.current !== null) {
      const a = routeMap(left.current, ["current"], current, optimized);
      const b = routeMap(right.current, ["optimized"], current, optimized);
      moveTogether(a, b);
      maps.push(a, b);
    } else {
      overlay.current = routeMap(left.current, ["current", "optimized"], current, optimized);
      maps.push(overlay.current);
    }
    return () => {
      for (const map of maps) map.remove();
      overlay.current = null;
    };
    // One run's routes do not change; a new view builds new maps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  useEffect(() => {
    const map = overlay.current;
    if (map === null) return;
    const apply = () => {
      for (const layer of ["current", "optimized"] as const) {
        if (map.getLayer(layer)) {
          map.setLayoutProperty(layer, "visibility", shown.has(layer) ? "visible" : "none");
        }
      }
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [shown, view]);

  if (view === "split") {
    return (
      <div className="split">
        <div ref={left} className="map large" aria-label="Map of the current routes" />
        <div ref={right} className="map large" aria-label="Map of the optimized routes" />
      </div>
    );
  }
  return <div ref={left} className="map large" aria-label="Map of current and optimized routes" />;
}
