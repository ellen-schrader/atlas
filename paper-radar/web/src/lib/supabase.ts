import { createClient } from "@supabase/supabase-js";

/** First non-empty, trimmed value. */
function pick(...vals: (string | undefined)[]): string | undefined {
  for (const v of vals) {
    const t = v?.trim();
    if (t) return t;
  }
  return undefined;
}

/** First value that actually looks like an http(s) URL (skips malformed ones). */
function pickUrl(...vals: (string | undefined)[]): string | undefined {
  for (const v of vals) {
    const t = v?.trim();
    if (t && /^https?:\/\/[^/]+/i.test(t)) return t;
  }
  return undefined;
}

// Accept either our VITE_* names or Supabase's dashboard NEXT_PUBLIC_* names.
const url = pickUrl(import.meta.env.VITE_SUPABASE_URL, import.meta.env.NEXT_PUBLIC_SUPABASE_URL);
const anon = pick(
  import.meta.env.VITE_SUPABASE_ANON_KEY,
  import.meta.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
);

export const isSupabaseConfigured = Boolean(url && anon);

if (!isSupabaseConfigured) {
  console.error(
    "Supabase env not usable — need a valid https URL (VITE_SUPABASE_URL or " +
      "NEXT_PUBLIC_SUPABASE_URL) and a key (VITE_SUPABASE_ANON_KEY or " +
      "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY) in web/.env.local, then restart `npm run dev`.",
  );
}

// Harmless placeholders when unconfigured so createClient() never throws at
// import (which blanks the screen). main.tsx renders a setup notice instead.
export const supabase = createClient(url ?? "http://localhost:54321", anon ?? "placeholder-anon-key");
