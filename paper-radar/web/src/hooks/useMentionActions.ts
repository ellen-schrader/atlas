import { useQueryClient } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

/** Mutations to mark @-mentions seen. Shared by the notifications bell and the
 *  dashboard's attention section. */
export function useMentionActions(userId: string) {
  const qc = useQueryClient();

  async function markSeen(paperId: string) {
    await supabase
      .from("mentions")
      .update({ seen_at: new Date().toISOString() })
      .eq("mentioned_user", userId)
      .eq("paper_id", paperId)
      .is("seen_at", null);
    void qc.invalidateQueries({ queryKey: ["mentions"] });
  }

  async function markAllSeen() {
    await supabase
      .from("mentions")
      .update({ seen_at: new Date().toISOString() })
      .eq("mentioned_user", userId)
      .is("seen_at", null);
    void qc.invalidateQueries({ queryKey: ["mentions"] });
  }

  return { markSeen, markAllSeen };
}
