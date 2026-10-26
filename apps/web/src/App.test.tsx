import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import { App } from "./App";

type Answer = { status: number; body: unknown };

/** Answers API calls by "METHOD /path", and records each request. */
function fakeApi(answers: Record<string, Answer | Answer[]>) {
  const calls: { key: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const key = `${request.method} ${new URL(request.url).pathname.replace(/^\/api/, "")}`;
    const text = await request.text();
    calls.push({ key, body: text ? JSON.parse(text) : undefined });
    const listed = answers[key];
    const answer = Array.isArray(listed) ? (listed.shift() ?? listed[0]) : listed;
    if (answer === undefined) throw new Error(`no fake answer for ${key}`);
    return new Response(JSON.stringify(answer.body), {
      status: answer.status,
      headers: { "Content-Type": "application/json" },
    });
  });
  return calls;
}

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

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
