import { useQuery } from "@tanstack/react-query";

import { fetchRecommendations, type RecScope } from "@/lib/api";

/** Personalized paper recommendations for the user in a lab. `scope="discover"`
 *  is the unseen feed; `scope="reading_list"` ranks the user's saved papers.
 *  Backed by the API (the embedding key is server-side), so it degrades to an
 *  error state — not a crash — when the service is unavailable. */
export function useRecommendations(teamId: string, scope: RecScope = "discover", limit = 12) {
  return useQuery({
    queryKey: ["recommendations", teamId, scope, limit],
    queryFn: () => fetchRecommendations(teamId, scope, limit),
    staleTime: 5 * 60 * 1000, // recompute at most every few minutes
    retry: false, // a 503 (no embeddings/service) shouldn't retry-storm
  });
}
