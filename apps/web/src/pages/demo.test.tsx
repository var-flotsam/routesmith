import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// The files the demo build publishes, as committed.
import committedAbout from "../../../../data/demo/result/about.json";
import committedShared from "../../../../data/demo/result/shared-run.json";
import { fakeApi } from "../test-helpers";
import { DemoPage, type DemoAbout } from "./DemoPage";

const ABOUT = committedAbout satisfies DemoAbout;

// The map needs WebGL, which the test browser lacks; it reports what it was given instead.
vi.mock("../map/RouteMap", () => ({
  RouteMap: (props: { current: unknown[]; optimized: unknown[]; view: string }) => (
    <p>
      {props.view} map of {props.current.length} current and {props.optimized.length} optimized
      routes
    </p>
  ),
}));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

// GitHub Pages serves the demo under the repository's name.
function serveDemo(
  shared: { status: number; body: unknown } = { status: 200, body: committedShared },
) {
  vi.stubEnv("BASE_URL", "/routesmith/");
  return fakeApi({
    "GET /routesmith/shared-run.json": shared,
    "GET /routesmith/about.json": { status: 200, body: ABOUT },
  });
}

function renderDemo() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DemoPage />
    </QueryClientProvider>,
  );
}

test("the demo shows the committed result side by side, from its two files alone", async () => {
  const calls = serveDemo();
  renderDemo();
  expect(await screen.findByRole("heading", { name: "Byram (demo)" })).toBeInTheDocument();
  expect(screen.getByRole("note")).toHaveTextContent(
    "Starboard Routing re-orders residential collection routes for automated side-loaders",
  );
  expect(screen.getByText(/^Route time:/)).toHaveTextContent(
    /^Route time: [\d.]+ h current, [\d.]+ h optimized \(-[\d.]+ h\)\. Wrong-side pickups: \d+ current, 0 optimized/,
  );
  expect(
    screen.getByText(/^The current route is synthetic\. It is a side-loader/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Of 754 stops, 714 are placed on a street/)).toHaveTextContent(
    "The other 40 would go to a planner's review: " +
      "About as near one street as another (9); No street near enough (31). " +
      "The result leaves them out of both routes",
  );
  expect(screen.getByText(/OpenStreetMap data as of 2026-10-23/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "OpenStreetMap contributors" })).toHaveAttribute(
    "href",
    "https://www.openstreetmap.org/copyright",
  );
  expect(
    await screen.findByText("split map of 1 current and 1 optimized routes"),
  ).toBeInTheDocument();
  expect(screen.getByRole("rowheader", { name: "Wrong-side pickups" })).toBeInTheDocument();
  // Nothing to sign in to or fill in, and nothing asked of an API.
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(calls.map((c) => c.key).sort()).toEqual([
    "GET /routesmith/about.json",
    "GET /routesmith/shared-run.json",
  ]);
});

test("on a phone the demo starts with one map", async () => {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query === "(max-width: 40rem)" }));
  serveDemo();
  renderDemo();
  expect(
    await screen.findByText("overlay map of 1 current and 1 optimized routes"),
  ).toBeInTheDocument();
});

test("a demo file that does not load says so", async () => {
  serveDemo({ status: 404, body: {} });
  renderDemo();
  expect(await screen.findByText(/The demo result did not load/)).toBeInTheDocument();
  expect(screen.queryByText("Loading…")).toBeNull();
});
