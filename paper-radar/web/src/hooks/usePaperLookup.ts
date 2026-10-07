import { useQuery } from "@tanstack/react-query";

import { resolvePaper, type ResolvedPaper } from "@/lib/api";
import { type Duplicate, fetchableUrl, findInLab } from "@/lib/paperLookup";

export interface PaperLookup {
  /** The fetchable URL that was resolved (a bare DOI becomes its doi.org link). */
  url: string;
  resolved: ResolvedPaper;
  /** Set when the lab already has this paper. */
  duplicate: Duplicate | null;
}

/** Resolve a pasted DOI / link without writing anything, and say whether the lab
 *  already has it — the preview behind Home's quick add. Runs only for a non-null
 *  `input`, so the caller decides when a lookup is worth a server round-trip
 *  (on paste and on ↵, not on every keystroke). */
export function usePaperLookup(teamId: string, input: string | null) {
  const url = input ? fetchableUrl(input) : "";
  return useQuery({
    queryKey: ["paper-lookup", teamId, url],
    enabled: Boolean(url),
    retry: false,
    staleTime: 5 * 60 * 1000,
    queryFn: async (): Promise<PaperLookup> => {
      const resolved = await resolvePaper(url);
      const duplicate = await findInLab(teamId, resolved);
      return { url, resolved, duplicate };
    },
  });
}
