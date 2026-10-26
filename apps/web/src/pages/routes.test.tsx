import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { fakeApi, ME, renderApp } from "../test-helpers";

const BYRAM = {
  id: "r1",
  name: "Byram",
  yard: { lon: -73.6463, lat: 41.0171 },
  disposal: { lon: -73.6463, lat: 41.0171 },
  capacity_carts: 420,
  max_route_hours: null,
};

const UPLOAD = {
  id: "up1",
  route_id: "r1",
  file_name: "stops.csv",
  state: "ready",
  rows_read: 754,
  rows_rejected: 0,
  stops_snapped: 740,
  stops_in_review: 14,
  stops_excluded: 0,
  rejected_rows: [],
  osm_snapshot: "2026-10-01",
  failure_reason: null,
  created_at: "2026-10-26T12:00:00Z",
};

test("a planner adds a route with its truck and sites", async () => {
  const calls = fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/routes": [
      { status: 200, body: [] },
      { status: 200, body: [BYRAM] },
    ],
    "POST /orgs/o1/routes": { status: 201, body: BYRAM },
  });
  renderApp("/orgs/o1");
  expect(await screen.findByText(/No routes yet/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Name"), "Byram");
  await userEvent.type(screen.getByLabelText("Yard (lon, lat)"), "-73.6463, 41.0171");
  await userEvent.type(screen.getByLabelText("Disposal site (lon, lat)"), "-73.6463,41.0171");
  await userEvent.type(screen.getByLabelText("Carts per load"), "420");
  await userEvent.click(screen.getByRole("button", { name: "Add route" }));
  expect(await screen.findByRole("link", { name: "Byram" })).toBeInTheDocument();
  expect(calls.find((c) => c.key === "POST /orgs/o1/routes")?.body).toEqual({
    name: "Byram",
    yard: { lon: -73.6463, lat: 41.0171 },
    disposal: { lon: -73.6463, lat: 41.0171 },
    capacity_carts: 420,
    max_route_hours: null,
  });
});

test("a route lists its stop lists and links the ones with stops to review", async () => {
  fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/routes/r1": { status: 200, body: BYRAM },
    "GET /orgs/o1/routes/r1/uploads": { status: 200, body: [UPLOAD] },
  });
  renderApp("/orgs/o1/routes/r1");
  expect(await screen.findByRole("heading", { name: "Byram" })).toBeInTheDocument();
  expect(screen.getByText("420 carts per load")).toBeInTheDocument();
  const review = await screen.findByRole("link", { name: "14" });
  expect(review).toHaveAttribute("href", "/orgs/o1/uploads/up1/review");
});

test("a stop list is sent as a file upload", async () => {
  const calls = fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/routes/r1": { status: 200, body: BYRAM },
    "GET /orgs/o1/routes/r1/uploads": { status: 200, body: [] },
    "POST /orgs/o1/routes/r1/uploads": { status: 202, body: { ...UPLOAD, state: "processing" } },
  });
  renderApp("/orgs/o1/routes/r1");
  const file = new File(["stop_id,current_sequence,lon,lat\n"], "stops.csv", { type: "text/csv" });
  await userEvent.upload(await screen.findByLabelText(/Stop list/), file);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  const sent = await waitFor(() => {
    const call = calls.find((c) => c.key === "POST /orgs/o1/routes/r1/uploads");
    expect(call).toBeDefined();
    return call;
  });
  expect(sent?.contentType).toBe("multipart/form-data");
  expect((sent?.body as FormData).get("file")).toHaveProperty("name", "stops.csv");
});
