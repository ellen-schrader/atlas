import { useQuery } from "@tanstack/react-query";

import { fetchTrialCountries } from "@/lib/trials";

/** The lab's trials' site countries, shared by the trial page, Compare and the
 *  All trials filter. Registry data changes rarely: refetched every 10 min. */
export function useTrialCountries(teamId: string) {
  return useQuery({
    queryKey: ["trial-countries", teamId],
    queryFn: () => fetchTrialCountries(teamId),
    staleTime: 10 * 60_000,
  });
}
