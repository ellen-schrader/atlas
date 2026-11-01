import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { supabase } from "@/lib/supabase";

type ReadStatus = "unread" | "reading" | "read";

/** Set a paper's reading progress for the user in a lab, from anywhere on Home.
 *  An upsert, so it works on a paper with no status row yet (a recommendation)
 *  and leaves `saved` alone on one that has. Refreshes what shows progress;
 *  `recommendations` only when asked, because refetching the row reshuffles it
 *  under the pointer. Says so on failure and resolves false. */
export function useSetReadStatus(userId: string, teamId: string) {
  const qc = useQueryClient();
  const toast = useToast();

  return async function setReadStatus(
    paperId: string,
    status: ReadStatus,
    { refreshRecommendations = false }: { refreshRecommendations?: boolean } = {},
  ): Promise<boolean> {
    const { error } = await supabase.from("paper_status").upsert(
      {
        user_id: userId,
        team_id: teamId,
        paper_id: paperId,
        status,
        // Explicit: there is no updated_at trigger (see BookmarkButton).
        updated_at: new Date().toISOString(),
      },
      { onConflict: "user_id,paper_id,team_id" },
    );
    if (error) {
      toast({ message: "Couldn’t update that paper. Try again." });
      return false;
    }
    const keys = ["reading-list", "read-this-week", "read-papers"];
    if (refreshRecommendations) keys.push("recommendations");
    for (const key of keys) void qc.invalidateQueries({ queryKey: [key] });
    return true;
  }
}
