import { useEffect, useMemo, useRef, useState } from "react";

import type { Schemas } from "../api/client";
import { truckAt, type Point } from "../map/playback";
import type { Trucks } from "../map/RouteMap";

// The longest route plays out in this many seconds of real time.
const PLAYBACK_LENGTH_S = 30;
const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_MINUTE = 60;

function clock(seconds: number): string {
  const hours = Math.floor(seconds / SECONDS_PER_HOUR);
  const minutes = Math.floor((seconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  return `${hours}:${String(minutes).padStart(2, "0")}`;
}

type Route = { path: [number, number][]; scorecard: { route_time_s: number } };

function positions(routes: Route[], elapsedS: number): (Point | null)[] {
  return routes.map((r) => truckAt(r.path, r.scorecard.route_time_s, elapsedS));
}

function finished(routes: Route[], elapsedS: number): number {
  return routes.filter((r) => r.scorecard.route_time_s <= elapsedS).length;
}

/** A clock that drives every truck along its route at once; trucks with shorter routes
 * get home first. Calls `onTrucks` with where each truck is. */
export function Playback({
  report,
  onTrucks,
}: {
  report: Schemas["RunReport"];
  onTrucks: (trucks: Trucks) => void;
}) {
  const current = report.current.routes;
  const optimized = report.optimized.routes;
  const endS = useMemo(
    () => Math.max(0, ...[...current, ...optimized].map((r) => r.scorecard.route_time_s)),
    [current, optimized],
  );
  const [elapsedS, setElapsedS] = useState(0);
  const [playing, setPlaying] = useState(false);
  const last = useRef<number | null>(null);

  useEffect(() => {
    onTrucks({ current: positions(current, elapsedS), optimized: positions(optimized, elapsedS) });
  }, [current, optimized, elapsedS, onTrucks]);

  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const step = (now: number) => {
      const before = last.current ?? now;
      last.current = now;
      const advance = ((now - before) / 1000) * (endS / PLAYBACK_LENGTH_S);
      setElapsedS((value) => {
        const next = Math.min(value + advance, endS);
        if (next >= endS) setPlaying(false);
        return next;
      });
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(frame);
      last.current = null;
    };
  }, [playing, endS]);

  function toggle() {
    if (!playing && elapsedS >= endS) setElapsedS(0);
    setPlaying(!playing);
  }

  return (
    <div className="playback">
      <button type="button" onClick={toggle}>
        {playing ? "Pause" : "Play"}
      </button>
      <input
        type="range"
        aria-label="Time into the day"
        min={0}
        max={Math.round(endS)}
        step={SECONDS_PER_MINUTE}
        value={Math.round(elapsedS)}
        onChange={(event) => {
          setPlaying(false);
          setElapsedS(Number(event.target.value));
        }}
      />
      <span>{clock(elapsedS)} into the day</span>
      <span className="muted">
        Current: {finished(current, elapsedS)} of {current.length} done. Optimized:{" "}
        {finished(optimized, elapsedS)} of {optimized.length} done.
      </span>
    </div>
  );
}
