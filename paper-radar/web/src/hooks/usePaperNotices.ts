import { useQuery, useQueryClient } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

/** A "your preprint has been published" notice (public.notifications), written
 *  by the daily preprint check (api/preprint_watch.py). */
export interface PaperNotice {
  id: string;
  created_at: string;
  seen_at: string | null;
  paper_id: string;
  kind: "preprint_published";
  payload: {
    title?: string | null;
    venue?: string | null;
    year?: number | null;
    preprint_venue?: string | null;
  };
}

/** This user's notices, newest first. RLS limits them to their own, in labs
 *  they are still in. */
export function usePaperNotices(userId: string) {
  return useQuery({
    queryKey: ["paper-notices", userId],
    queryFn: async (): Promise<PaperNotice[]> => {
      const { data, error } = await supabase
        .from("notifications")
        .select("id, created_at, seen_at, paper_id, kind, payload")
        .eq("user_id", userId)
        .order("created_at", { ascending: false })
        .limit(50);
      if (error) throw error;
      return (data ?? []) as PaperNotice[];
    },
  });
}

export function usePaperNoticeActions(userId: string) {
  const qc = useQueryClient();

  async function markSeen(id: string) {
    await supabase
      .from("notifications")
      .update({ seen_at: new Date().toISOString() })
      .eq("id", id)
      .is("seen_at", null);
    void qc.invalidateQueries({ queryKey: ["paper-notices"] });
  }

  async function markAllSeen() {
    await supabase
      .from("notifications")
      .update({ seen_at: new Date().toISOString() })
      .eq("user_id", userId)
      .is("seen_at", null);
    void qc.invalidateQueries({ queryKey: ["paper-notices"] });
  }

  return { markSeen, markAllSeen };
}
