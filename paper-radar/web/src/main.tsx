import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "@/App";
import { SetupNotice } from "@/components/SetupNotice";
import { ThemeProvider } from "@/components/ThemeProvider";
import { isSupabaseConfigured } from "@/lib/supabase";
import "@/index.css";

const queryClient = new QueryClient();

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
