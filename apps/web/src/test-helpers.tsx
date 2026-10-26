import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import { App } from "./App";

type Answer = { status: number; body: unknown };

export type Call = { key: string; body: unknown; contentType: string | null };

/** Answers API calls by "METHOD /path", and records each request; a list answers in turn. */
export function fakeApi(answers: Record<string, Answer | Answer[]>): Call[] {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    let key: string;
    let body: unknown;
    let contentType: string | null;
    if (input instanceof Request) {
      key = `${input.method} ${new URL(input.url).pathname.replace(/^\/api/, "")}`;
      contentType = input.headers.get("Content-Type");
      const text = await input.text();
      body = contentType?.includes("json") && text ? JSON.parse(text) : text || undefined;
    } else {
      // A direct fetch, as for file uploads: the body is the FormData itself.
      key = `${init?.method ?? "GET"} ${new URL(String(input)).pathname.replace(/^\/api/, "")}`;
      body = init?.body;
      contentType = body instanceof FormData ? "multipart/form-data" : null;
    }
    calls.push({ key, body, contentType });
    const listed = answers[key];
    const answer = Array.isArray(listed) ? (listed.length > 1 ? listed.shift() : listed[0]) : listed;
    if (answer === undefined) throw new Error(`no fake answer for ${key}`);
    return new Response(JSON.stringify(answer.body), {
      status: answer.status,
      headers: { "Content-Type": "application/json" },
    });
  });
  return calls;
}

/** The whole app at `path`, with a fresh query cache. */
export function renderApp(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const ME = {
  id: "u1",
  email: "planner@example.com",
  organizations: [{ org_id: "o1", name: "Hauler", role: "owner" }],
};
