import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

/** Stamp the visit this long after arriving, if the reader hasn't left first. */
const MARK_AFTER_MS = 10_000;
/** A visit shorter than this isn't one: it is also what React StrictMode's
 *  dev-only mount → unmount → mount looks like, which must not reset the count
 *  before it has been read. */
const MIN_VISIT_MS = 1_000;

/** "n new papers since your last visit" for Home (docs/dashboard.md §3.1).
 *
 *  Reads the count on arrival, then stamps the visit after 10s on the page or
 *  when Home unmounts — so the number shown isn't reset under the reader, and
 *  coming back later counts from when they left. `data` is null before a first
 *  visit has ever been recorded. */
export function useNewSinceLastVisit(teamId: string) {
  const query = useQuery({
    queryKey: ["new-since-visit", teamId],
    // Fetched once per arrival: a refetch mid-visit would read our own stamp and
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

  useEffect(() => {
    const arrived = Date.now();
    let marked = false;
    const mark = () => {
      if (marked) return;
      marked = true;
      void supabase.rpc("mark_team_visit", { p_team: teamId });
    };
    const timer = window.setTimeout(mark, MARK_AFTER_MS);
    return () => {
      window.clearTimeout(timer);
      if (Date.now() - arrived >= MIN_VISIT_MS) mark();
    };
  }, [teamId]);

  return query;
}
