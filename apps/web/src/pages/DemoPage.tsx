import { useQuery } from "@tanstack/react-query";

import type { Schemas } from "../api/client";
import type { View } from "../map/RouteMap";
import { REASONS } from "./reasons";
import { Headline, ReportView } from "./ReportView";

/** What the demo result was built from (`starboard.worker.demo_result.DemoAbout`). */
export type DemoAbout = {
  place: string;
  current_route_description: string;
  stops_in_file: number;
  stops_placed: number;
  stops_in_review: Record<string, number>;
  osm_snapshot: string | null;
  input_sha256: Record<string, string>;
};

type Demo = { shared: Schemas["SharedRun"]; about: DemoAbout };

// The demo build serves data/demo/result as its static files (vite.config.ts).
async function demoFile<T>(name: string): Promise<T> {
  const response = await fetch(`${window.location.origin}${import.meta.env.BASE_URL}${name}`);
  if (!response.ok) throw new Error(`${name} did not load (${response.status})`);
  return (await response.json()) as T;
}

// Set where the demo is published (.github/workflows/pages.yml); absent in a local build.
const REPOSITORY = import.meta.env.VITE_REPOSITORY_URL;

// The phone width in styles.css. Two maps side by side do not fit a phone, and stacked
// they cannot be compared, so a phone starts with one map.
const PHONE = "(max-width: 40rem)";

function startingView(): View {
  const phone = typeof window.matchMedia === "function" && window.matchMedia(PHONE).matches;
  return phone ? "overlay" : "split";
}

function About({ about, finishedAt }: { about: DemoAbout; finishedAt: string | null }) {
  const reviewed = Object.entries(about.stops_in_review);
  const inReview = reviewed.reduce((total, [, count]) => total + count, 0);
  return (
    <>
      <h2>About this demo</h2>
      <p>
        {about.place}. Of {about.stops_in_file.toLocaleString("en-US")} stops,{" "}
        {about.stops_placed.toLocaleString("en-US")} are placed on a street.
        {inReview > 0 && (
          <>
            {" "}
            The other {inReview} would go to a planner&apos;s review:{" "}
            {reviewed
              .map(([reason, count]) => `${REASONS[reason] ?? reason} (${count})`)
              .join("; ")}
            . The result leaves them out of both routes, as a planner can before solving.
          </>
        )}
      </p>
      <p className="muted">
        {finishedAt &&
          `Computed ${new Date(finishedAt).toLocaleDateString("en-US", { dateStyle: "long", timeZone: "UTC" })} from `}
        OpenStreetMap data{about.osm_snapshot && ` as of ${about.osm_snapshot.slice(0, 10)}`}, ©{" "}
        <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> (ODbL).{" "}
        {REPOSITORY && (
          <a href={`${REPOSITORY}/blob/main/data/demo/PROVENANCE.md`}>How the demo data was made</a>
        )}
      </p>
    </>
  );
}

function DemoResult({ shared, about }: Demo) {
  return (
    <section>
      <h1>{shared.route_name}</h1>
      <Headline report={shared.report} />
      <p>The current route is synthetic. {about.current_route_description}</p>
      <ReportView report={shared.report} initialView={startingView()}>
        <About about={about} finishedAt={shared.finished_at} />
      </ReportView>
    </section>
  );
}

/** The public demo: one precomputed result, with no sign-in and no API (ADR-0007). */
export function DemoPage() {
  const demo = useQuery({
    queryKey: ["demo"],
    queryFn: async (): Promise<Demo> => {
      const [shared, about] = await Promise.all([
        demoFile<Schemas["SharedRun"]>("shared-run.json"),
        demoFile<DemoAbout>("about.json"),
      ]);
      return { shared, about };
    },
  });
  return (
    <div className="shell">
      <header>
        <strong>Starboard Routing</strong>
        <span className="muted">Demo</span>
      </header>
      <main>
        <p className="banner" role="note">
          Starboard Routing re-orders residential collection routes for automated side-loaders,
          whose arm reaches only carts on the truck&apos;s right. This demo shows a result computed
          in advance for a synthetic route on public address data; nothing is solved in your
          browser. To run it yourself, see the{" "}
          {REPOSITORY ? <a href={`${REPOSITORY}#readme`}>README</a> : "README"}.
        </p>
        {demo.isPending && <p>Loading…</p>}
        {demo.isError && (
          <p className="error">The demo result did not load. Try reloading the page.</p>
        )}
        {demo.data && <DemoResult {...demo.data} />}
      </main>
    </div>
  );
}
