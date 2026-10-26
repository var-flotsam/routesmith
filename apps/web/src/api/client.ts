// The typed API client. Types come from the API's OpenAPI spec (`pnpm api-types`);
// every screen reads and writes through this, via TanStack Query.
import createClient from "openapi-fetch";

import type { paths } from "./schema";

// The API is proxied under /api on the app's own origin (see vite.config.ts).
export const api = createClient<paths>({
  baseUrl: `${window.location.origin}/api`,
  credentials: "include",
  // Looked up on each call, so tests can stand in for the network.
  fetch: (request) => globalThis.fetch(request),
});

export type Schemas = import("./schema").components["schemas"];

/** An answer the API gave instead of the data, with its status. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `the API answered ${status}`);
  }
}

/** The data of an openapi-fetch answer, or an ApiError carrying the API's own reason. */
export function dataOf<T>(answer: { data?: T; error?: unknown; response: Response }): T {
  if (answer.data !== undefined) return answer.data;
  const detail = (answer.error as { detail?: unknown } | undefined)?.detail;
  throw new ApiError(answer.response.status, detail);
}
