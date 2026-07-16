import { useQuery } from "@tanstack/react-query";

import { fetchRecommendations, isTransientApiError, type RecScope } from "@/lib/api";

// Poll a cold-boot-shaped failure every 10s, but give up after ~100s (triple
// a typical boot) so a machine that never comes up doesn't keep an open tab
// requesting — and, via Fly's idle detection, billing — forever.
const COLD_BOOT_POLL_MS = 10_000;
const COLD_BOOT_POLL_MAX = 10;

/** True while a recommendations query's failure looks like the API machine's
 *  cold boot AND the hook is still polling for it to wake — the state where
 *  "waking, will appear shortly" is honest copy. */
export function isWakingRecommendations(recs: {
  isError: boolean;
  error: unknown;
  errorUpdateCount: number;
}): boolean {
  return (
    recs.isError && isTransientApiError(recs.error) && recs.errorUpdateCount < COLD_BOOT_POLL_MAX
  );
}

/** Personalized paper recommendations for the user in a lab. `scope="discover"`
 *  is the unseen feed; `scope="reading_list"` ranks the user's saved papers.
 *  Backed by the API (the embedding key is server-side), so it degrades to an
 *  error state — not a crash — when the service is unavailable. */
export function useRecommendations(
  teamId: string,
  scope: RecScope = "discover",
  limit = 12,
  enabled = true,
) {
  return useQuery({
    queryKey: ["recommendations", teamId, scope, limit],
    queryFn: () => fetchRecommendations(teamId, scope, limit),
    enabled,
    staleTime: 5 * 60 * 1000, // recompute at most every few minutes
    // Fail fast so the dashboard renders instantly with a fallback instead of
    // holding skeletons through the API machine's ~30s cold boot — but keep
    // polling (bounded) while the failure looks like that cold boot, so the
    // cards pop in on their own once the machine wakes.
    retry: false,
    refetchInterval: (query) =>
      query.state.status === "error" &&
      isTransientApiError(query.state.error) &&
      query.state.errorUpdateCount < COLD_BOOT_POLL_MAX
        ? COLD_BOOT_POLL_MS
        : false,
  });
}
