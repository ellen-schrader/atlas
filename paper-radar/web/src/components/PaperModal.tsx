import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { PaperDetail } from "@/components/PaperDetail";
import { Modal } from "@/components/ui/modal";
import { supabase } from "@/lib/supabase";
import type { PaperPost } from "@/lib/types";

const PaperModalContext = createContext<{ openPaper: (paperId: string) => void }>({
  openPaper: () => {},
});

export const usePaperModal = () => useContext(PaperModalContext);

/** Provides `openPaper(paperId)` app-wide. Fetches the lab's post for that paper
 *  and shows the detail + engagement in a modal, so any list (papers, dashboard)
 *  can open the same view. */
export function PaperModalProvider({
  teamId,
  userId,
  children,
}: {
  teamId: string;
  userId: string;
  children: ReactNode;
}) {
  const [paperId, setPaperId] = useState<string | null>(null);

  const { data: post, isLoading } = useQuery({
    queryKey: ["paper-post", teamId, paperId],
    enabled: paperId !== null,
    queryFn: async (): Promise<PaperPost | null> => {
      const { data, error } = await supabase
        .from("paper_posts")
        .select("id, posted_at, note, posted_by, posted_by_label, tags, papers(*)")
        .eq("team_id", teamId)
        .eq("paper_id", paperId!)
        .maybeSingle();
      if (error) throw error;
      return (data as unknown as PaperPost) ?? null;
    },
  });

  return (
    <PaperModalContext.Provider value={{ openPaper: setPaperId }}>
      {children}
      <Modal open={paperId !== null} onClose={() => setPaperId(null)}>
        {post ? (
          <PaperDetail key={post.id} post={post} teamId={teamId} userId={userId} />
        ) : (
          <div className="p-6 text-sm text-muted">{isLoading ? "Loading…" : "Paper not available."}</div>
        )}
      </Modal>
    </PaperModalContext.Provider>
  );
}
