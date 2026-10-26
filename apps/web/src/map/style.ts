// What the maps look like; kept apart from the map components so pages can show the same
// colours in legends without loading the map library.

// Free vector tiles from OpenStreetMap data, no key needed (https://openfreemap.org).
export const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

// Today's routes in one muted colour; each optimized truck in its own colour.
export const CURRENT_COLOUR = "#9ca3af";
const TRUCK_COLOURS = ["#2563eb", "#16a34a", "#db2777", "#ea580c", "#7c3aed", "#0891b2"];

export function truckColour(index: number): string {
  return TRUCK_COLOURS[index % TRUCK_COLOURS.length] ?? CURRENT_COLOUR;
}
