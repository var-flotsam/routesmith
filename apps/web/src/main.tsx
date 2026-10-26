import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import { DemoPage } from "./pages/DemoPage";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

const root = document.getElementById("root");
if (root === null) throw new Error("index.html has no #root");

// The demo build (`pnpm build:demo`, ADR-0007) is one page, with no routes and no API.
const page =
  import.meta.env.MODE === "demo" ? (
    <DemoPage />
  ) : (
    <BrowserRouter>
      <App />
    </BrowserRouter>
  );

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>{page}</QueryClientProvider>
  </StrictMode>,
);
