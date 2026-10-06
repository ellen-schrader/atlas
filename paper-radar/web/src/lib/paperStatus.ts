import type { SupabaseClient } from "@supabase/supabase-js";

/** Reading progress. Independent of `saved` — see 20261006120000. */
export type Progress = "unread" | "reading" | "read";

/**
 * Drop a paper_status row that has fallen back to meaning nothing: not saved,
 * and no reading progress.
 *
 * It matters because `recommend_v2` excludes every paper that has ANY
 * paper_status row, on the assumption that a row means you have engaged with it.
 * Leave an all-default row behind and the paper disappears from Discover
 * forever — un-saving it would quietly bury it instead of putting it back in
 * circulation, which is the opposite of what un-saving means.
 *
 * Scoped by `saved = false and status = 'unread'` so it can never race with a
 * concurrent save or a mark-read: if either landed first, the row no longer
 * matches and the delete is a no-op.
 */
export async function deleteIfDefault(
  client: SupabaseClient,
  userId: string,
  teamId: string,
  paperId: string,
): Promise<void> {
  await client
    .from("paper_status")
    .delete()
    .eq("user_id", userId)
    .eq("team_id", teamId)
    .eq("paper_id", paperId)
    .eq("saved", false)
    .eq("status", "unread");
}
