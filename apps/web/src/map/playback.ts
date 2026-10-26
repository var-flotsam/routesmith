// Where each truck is a given time into its route, for playback. Every truck is taken to
// drive its path at an even pace that finishes in its route's time, so trucks on the
// same clock show which route finishes first. The route times come from the API.

export type Point = [number, number]; // [lon, lat]

function distance(a: Point, b: Point): number {
  // Degrees, with longitude shrunk by latitude: enough to share a path out by length.
  const dx = (b[0] - a[0]) * Math.cos((((a[1] + b[1]) / 2) * Math.PI) / 180);
  return Math.hypot(dx, b[1] - a[1]);
}

/** The point `fraction` (0 to 1) of the way along `path`, by length. */
export function pointAlong(path: Point[], fraction: number): Point | null {
  const first = path[0];
  if (first === undefined) return null;
  const lengths = path.slice(1).map((point, k) => distance(path[k] ?? point, point));
  const total = lengths.reduce((sum, length) => sum + length, 0);
  let left = Math.min(Math.max(fraction, 0), 1) * total;
  for (let k = 0; k < lengths.length; k += 1) {
    const length = lengths[k] ?? 0;
    const a = path[k] ?? first;
    const b = path[k + 1] ?? a;
    if (left <= length) {
      const t = length === 0 ? 0 : left / length;
      return [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];
    }
    left -= length;
  }
  return path[path.length - 1] ?? first;
}

/** Where a truck is `elapsedS` seconds into a route that takes `routeTimeS` seconds. */
export function truckAt(path: Point[], routeTimeS: number, elapsedS: number): Point | null {
  return pointAlong(path, routeTimeS > 0 ? elapsedS / routeTimeS : 1);
}
