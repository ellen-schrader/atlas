import { useQuery } from "@tanstack/react-query";

import { fetchRecommendations, isTransientApiError, type RecScope } from "@/lib/api";

/** Personalized paper recommendations for the user in a lab. `scope="discover"`
 *  is the unseen feed; `scope="reading_list"` ranks the user's saved papers.
 *  Backed by the API (the embedding key is server-side), so it degrades to an
 *  error state — not a crash — when the service is unavailable. */
export function useRecommendations(teamId: string, scope: RecScope = "discover", limit = 12) {
  return useQuery({
    queryKey: ["recommendations", teamId, scope, limit],
    queryFn: () => fetchRecommendations(teamId, scope, limit),
    staleTime: 5 * 60 * 1000, // recompute at most every few minutes
    // Fail fast so the dashboard renders instantly with a fallback instead of
    // holding skeletons through the API machine's ~30s cold boot — but keep
    // polling while the failure looks like that cold boot, so the cards pop
    // in on their own once the machine wakes.
    retry: false,
    refetchInterval: (query) =>
      query.state.status === "error" && isTransientApiError(query.state.error) ? 10_000 : false,
  });
}
