import { existsSync } from "node:fs";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The demo build (mode "demo", ADR-0007) serves the precomputed demo result as its static
// files; the page fetches these two by name.
const DEMO_RESULT = "../../data/demo/result";
const DEMO_FILES = ["shared-run.json", "about.json"];

// The path the demo is served under, such as /routesmith/ on GitHub Pages; always with a
// trailing slash, since the page adds file names to it.
function demoBase(): string {
  const base = process.env.STARBOARD_WEB_BASE ?? "/";
  if (!base.startsWith("/")) {
    // Git Bash turns /routesmith/ into a Windows path unless told not to.
    throw new Error(
      `STARBOARD_WEB_BASE must be a path such as /routesmith/, not ${base}; ` +
        "in Git Bash, set MSYS2_ENV_CONV_EXCL=STARBOARD_WEB_BASE",
    );
  }
  return base.endsWith("/") ? base : `${base}/`;
}

// In development the API runs on :8000 (Docker Compose or uvicorn); the app reaches it
// under /api so the session cookie stays on one origin.
export default defineConfig(({ mode }) => {
  const demo = mode === "demo";
  for (const name of demo ? DEMO_FILES : []) {
    // Vite skips a missing public folder silently, which would publish a page with no data.
    if (!existsSync(new URL(`${DEMO_RESULT}/${name}`, import.meta.url))) {
      throw new Error(`the demo build needs data/demo/result/${name}`);
    }
  }
  return {
    plugins: [react()],
    base: demo ? demoBase() : "/",
    publicDir: demo ? DEMO_RESULT : "public",
    server: {
      port: 5173,
      proxy: {
        "/api": {
          // Docker Compose points this at its api service.
          target: process.env.STARBOARD_API_TARGET ?? "http://localhost:8000",
          rewrite: (path) => path.replace(/^\/api/, ""),
        },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["src/test-setup.ts"],
    },
  };
});
