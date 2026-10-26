// What the maps look like; kept apart from the map components so pages can show the same
// colours in legends without loading the map library.
import type { StyleSpecification } from "maplibre-gl";

// Free vector tiles from OpenStreetMap data, no key needed (https://openfreemap.org).
export const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

// When the basemap cannot load (offline, or its server is down), the routes still draw,
// on a plain background.
export const PLAIN_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#f3f4f6" } }],
};

// Today's routes in one grey, dark enough (about 4.8:1 on white) to read on a map of its
// own; each optimized truck in its own colour.
export const CURRENT_COLOUR = "#6b7280";
const TRUCK_COLOURS = ["#2563eb", "#16a34a", "#db2777", "#ea580c", "#7c3aed", "#0891b2"];

export function truckColour(index: number): string {
  return TRUCK_COLOURS[index % TRUCK_COLOURS.length] ?? CURRENT_COLOUR;
}
