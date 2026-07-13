import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "@/App";
import { SetupNotice } from "@/components/SetupNotice";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ApiError, isTransientApiError } from "@/lib/api";
import { isSupabaseConfigured } from "@/lib/supabase";
import "@/index.css";

// The API machine cold-boots after an idle spell (~30 s of connection
// failures / proxy 502s). Ride those out with a long backoff for every query
// that hits it; deterministic API answers (4xx, and app-level 500/503 like
// "Embeddings unavailable") never heal on retry, so surface them
// immediately. Non-API queries (Supabase) keep the library's default count.
// Per-query `retry` overrides still win (e.g. useRecommendations opts out).
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) =>
        error instanceof ApiError
          ? isTransientApiError(error) && failureCount < 6
          : failureCount < 3,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      {isSupabaseConfigured ? (
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      ) : (
        <SetupNotice />
      )}
    </ThemeProvider>
  </React.StrictMode>,
);
