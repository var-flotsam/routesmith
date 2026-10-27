import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { fakeApi, ME, renderApp } from "../test-helpers";

const YARD = { lon: -73.6463, lat: 41.0171, address: "1 MILL ST, GREENWICH, CT, 06830" };
const DISPOSAL = { lon: -73.65, lat: 41.02, address: null };

const BYRAM = {
  id: "r1",
  name: "Byram",
  yard: YARD,
  disposal: DISPOSAL,
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
    "GET /orgs/o1/places": [
      { status: 200, body: [YARD] },
      { status: 200, body: [DISPOSAL] },
    ],
    "POST /orgs/o1/routes": { status: 201, body: BYRAM },
  });
  renderApp("/orgs/o1");
  expect(await screen.findByText(/No routes yet/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Name"), "Byram");
  await userEvent.type(screen.getByLabelText("Yard address"), "1 Mill St, Greenwich, CT");
  await userEvent.type(screen.getByLabelText("Disposal site address"), "41.02, -73.65");
  expect(await screen.findByText(`Found: ${YARD.address}`)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Carts per load"), "420");
  await userEvent.click(screen.getByRole("button", { name: "Add route" }));
  expect(await screen.findByRole("link", { name: "Byram" })).toBeInTheDocument();
  expect(calls.find((c) => c.key === "POST /orgs/o1/routes")?.body).toEqual({
    name: "Byram",
    yard: YARD,
    disposal: DISPOSAL,
    capacity_carts: 420,
    max_route_hours: null,
  });
  const asked = calls
    .filter((c) => c.key === "GET /orgs/o1/places")
    .map((c) => new URLSearchParams(c.query).get("address"));
  expect(asked).toEqual(["1 Mill St, Greenwich, CT", "41.02, -73.65"]);
});

test("pressing Enter shows the places that fit, to pick from", async () => {
  const other = { ...YARD, lon: -73.7, address: "1 MILL ST, STAMFORD, CT, 06902" };
  fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/routes": { status: 200, body: [] },
    "GET /orgs/o1/places": [
      { status: 200, body: [DISPOSAL] },
      { status: 200, body: [YARD, other] },
    ],
  });
  renderApp("/orgs/o1");
  await userEvent.type(await screen.findByLabelText("Name"), "Byram");
  await userEvent.type(screen.getByLabelText("Disposal site address"), "41.02, -73.65");
  await userEvent.type(screen.getByLabelText("Yard address"), "1 Mill St{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Several places fit the yard's address; pick one.",
  );
  const choices = await screen.findByRole("group", {
    name: "Several places fit the yard address. Which one?",
  });
  expect(choices).toHaveTextContent(other.address);
});

test("a lookup the address service did not answer is asked again", async () => {
  fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/routes": { status: 200, body: [] },
    "GET /orgs/o1/places": [
      { status: 502, body: { detail: "the geocoder did not answer" } },
      { status: 200, body: [YARD] },
    ],
  });
  renderApp("/orgs/o1");
  const yard = await screen.findByLabelText("Yard address");
  await userEvent.type(yard, "1 Mill St");
  await userEvent.tab();
  expect(await screen.findByText(/The address service did not answer/)).toBeInTheDocument();
  expect(yard).toHaveAttribute("aria-invalid", "true");
  await userEvent.click(yard);
  await userEvent.tab();
  expect(await screen.findByText(`Found: ${YARD.address}`)).toBeInTheDocument();
  expect(yard).toHaveAttribute("aria-invalid", "false");
});

test("when several places fit an address, the planner picks one", async () => {
  const other = { ...YARD, lon: -73.7, address: "1 MILL ST, STAMFORD, CT, 06902" };
  const calls = fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/routes": [
      { status: 200, body: [] },
      { status: 200, body: [BYRAM] },
    ],
    "GET /orgs/o1/places": [
      { status: 200, body: [YARD, other] },
      { status: 200, body: [DISPOSAL] },
    ],
    "POST /orgs/o1/routes": { status: 201, body: BYRAM },
  });
  renderApp("/orgs/o1");
  await userEvent.type(await screen.findByLabelText("Name"), "Byram");
  await userEvent.type(screen.getByLabelText("Yard address"), "1 Mill St");
  await userEvent.type(screen.getByLabelText("Disposal site address"), "41.02, -73.65");
  await userEvent.click(screen.getByRole("button", { name: "Add route" }));
  expect(await screen.findByText(/Several places fit the yard's address/)).toBeInTheDocument();
  expect(calls.some((c) => c.key === "POST /orgs/o1/routes")).toBe(false);
  await userEvent.click(screen.getByRole("radio", { name: other.address }));
  await userEvent.click(screen.getByRole("button", { name: "Add route" }));
  await waitFor(() =>
    expect(calls.find((c) => c.key === "POST /orgs/o1/routes")?.body).toMatchObject({
      yard: other,
    }),
  );
});

test("an address that names no place says so and adds no route", async () => {
  const calls = fakeApi({
    "GET /me": { status: 200, body: ME },
    "GET /orgs/o1/routes": { status: 200, body: [] },
    "GET /orgs/o1/places": { status: 200, body: [] },
  });
  renderApp("/orgs/o1");
  await userEvent.type(await screen.findByLabelText("Yard address"), "nowhere");
  await userEvent.tab();
  expect(await screen.findByText(/No place found for that address/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Name"), "Byram");
  await userEvent.type(screen.getByLabelText("Disposal site address"), "nowhere");
  await userEvent.click(screen.getByRole("button", { name: "Add route" }));
  expect(await screen.findByText("No place found for the yard's address.")).toBeInTheDocument();
  expect(calls.some((c) => c.key === "POST /orgs/o1/routes")).toBe(false);
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
  expect(
    screen.getByText(
      `Yard: ${YARD.address}. Disposal site: 41.020000, -73.650000 (latitude, longitude).`,
    ),
  ).toBeInTheDocument();
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
