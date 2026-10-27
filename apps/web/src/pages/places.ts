/** A yard or disposal site as the planner reads it: its matched address, or its point. */
export function describe(place: { address: string | null; lat: number; lon: number }): string {
  return place.address ?? `${place.lat.toFixed(6)}, ${place.lon.toFixed(6)} (latitude, longitude)`;
}
