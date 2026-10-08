import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

/** Stamp the visit this long after arriving, if the reader hasn't left first. */
const MARK_AFTER_MS = 10_000;
/** A visit shorter than this isn't one: it is also what React StrictMode's
 *  dev-only mount → unmount → mount looks like, which must not reset the count
 *  before it has been read. */
const MIN_VISIT_MS = 1_000;
/** Coming back to a tab left in the background this long is a new visit. */
const RETURN_AFTER_MS = 30 * 60 * 1000;

function markVisit(teamId: string) {
  // .then() is what sends it: a supabase-js query builder is lazy, and a bare
  // `void supabase.rpc(...)` never leaves the browser.
  supabase
    .rpc("mark_team_visit", { p_team: teamId })
    .then(({ error }) => error && console.warn("mark_team_visit failed:", error.message));
}

/** "n new papers since your last visit" for Home (docs/dashboard.md §3.1).
 *
 *  Reads the count on arrival, then stamps the visit after 10s on the page or
 *  when the reader leaves (navigating away, or closing the tab) — so the number
 *  shown isn't reset under the reader, and coming back later counts from when
 *  they left. A tab left in the background for 30 minutes counts as a new
 *  visit when it comes back. `data` is null before a first visit is recorded. */
export function useNewSinceLastVisit(teamId: string) {
  const query = useQuery({
    queryKey: ["new-since-visit", teamId],
    // Fetched once per visit: a refetch mid-visit would read our own stamp and
    // drop the count to 0 while the reader is looking at it.
    staleTime: Infinity,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    queryFn: async (): Promise<number | null> => {
      const { data, error } = await supabase.rpc("new_since_last_visit", { p_team: teamId });
      if (error) throw error;
      return (data ?? null) as number | null;
    },
  });
  const { refetch } = query;

  useEffect(() => {
    let arrived = Date.now();
    let marked = false;
    let hiddenAt: number | null = null;
    let timer = 0;

    const mark = () => {
      if (marked) return;
      marked = true;
      window.clearTimeout(timer);
      markVisit(teamId);
    };
    const leave = () => {
      if (Date.now() - arrived >= MIN_VISIT_MS) mark();
    };
    const start = () => {
      arrived = Date.now();
      marked = false;
      timer = window.setTimeout(mark, MARK_AFTER_MS);
    };

    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        hiddenAt = Date.now();
        return;
      }
      const away = hiddenAt == null ? 0 : Date.now() - hiddenAt;
      hiddenAt = null;
      if (away >= RETURN_AFTER_MS) {
        // A new visit: stamp the old one if it never was, read the count
        // against it, then start counting this one.
        window.clearTimeout(timer);
        void refetch().then(start);
      }
    };

    start();
    document.addEventListener("visibilitychange", onVisibility);
    // Closing the tab never unmounts React; pagehide is the last chance.
    window.addEventListener("pagehide", leave);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", leave);
      leave();
    };
  }, [teamId, refetch]);

  return query;
}
