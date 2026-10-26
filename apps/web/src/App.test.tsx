import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { fakeApi, renderApp } from "./test-helpers";

const ME = { id: "u1", email: "planner@example.com", organizations: [] };

test("someone not signed in asks for a sign-in link", async () => {
  const calls = fakeApi({
    "GET /me": { status: 401, body: { detail: "not signed in" } },
    "POST /auth/magic-link": { status: 202, body: null },
  });
  renderApp();
  await userEvent.type(await screen.findByLabelText("Email"), "planner@example.com");
  await userEvent.click(screen.getByRole("button", { name: "Email me a sign-in link" }));
  expect(await screen.findByText("Check your email")).toBeInTheDocument();
  expect(calls.find((c) => c.key === "POST /auth/magic-link")?.body).toEqual({
    email: "planner@example.com",
  });
});

test("a signed-in planner sees their organizations and starts one", async () => {
  const calls = fakeApi({
    "GET /me": [
      { status: 200, body: ME },
      {
        status: 200,
        body: { ...ME, organizations: [{ org_id: "o1", name: "Hauler", role: "owner" }] },
      },
    ],
    "POST /orgs": { status: 201, body: { id: "o1", name: "Hauler" } },
  });
  renderApp();
  expect(await screen.findByText(/not in an organization yet/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("New organization"), "Hauler");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));
  expect(await screen.findByText("Hauler")).toBeInTheDocument();
  expect(calls.find((c) => c.key === "POST /orgs")?.body).toEqual({ name: "Hauler" });
});

test("an API failure is shown, not swallowed", async () => {
  fakeApi({ "GET /me": { status: 500, body: { detail: "the database is down" } } });
  renderApp();
  expect(await screen.findByText("the database is down")).toBeInTheDocument();
});
