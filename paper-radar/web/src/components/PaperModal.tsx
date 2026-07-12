import { createContext, useContext, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { PaperDetail } from "@/components/PaperDetail";
import { Modal } from "@/components/ui/modal";
import { useReadingList } from "@/hooks/useReadingList";
import { supabase } from "@/lib/supabase";
import type { PaperPost } from "@/lib/types";

const PaperModalContext = createContext<{ openPaper: (paperId: string) => void }>({
  openPaper: () => {},
});

export const usePaperModal = () => useContext(PaperModalContext);

/** Provides `openPaper(paperId)` app-wide. The open paper lives in the URL as
 *  `?paper=<id>`, so detail links are shareable, the back button closes the
 *  modal, and a refresh reopens it. Fetches the lab's post for that paper and
 *  shows the detail + engagement over whatever page you're on. */
export function PaperModalProvider({
  teamId,
  userId,
  children,
}: {
  teamId: string;
  userId: string;
  children: ReactNode;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const paperId = searchParams.get("paper");

  const openPaper = (id: string) =>
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("paper", id);
      return next;
    });

  const close = () =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("paper");
        return next;
      },
      { replace: true },
    );

  const { data: reading } = useReadingList(userId, teamId);
  const bookmarked = (reading ?? []).some((r) => r.paper_id === paperId);

  const { data: post, isLoading } = useQuery({
    queryKey: ["paper-post", teamId, paperId],
    enabled: paperId !== null,
    queryFn: async (): Promise<PaperPost | null> => {
      const { data, error } = await supabase
        .from("paper_posts")
        .select(
          "id, posted_at, note, posted_by, posted_by_label, tags, papers(*), poster:profiles!paper_posts_posted_by_fkey(display_name)",
        )
        .eq("team_id", teamId)
        .eq("paper_id", paperId!)
        .maybeSingle();
      if (error) throw error;
      return (data as unknown as PaperPost) ?? null;
    },
  });

  return (
    <PaperModalContext.Provider value={{ openPaper }}>
      {children}
      <Modal open={paperId !== null} onClose={close} label={post?.papers.title ?? "Paper"}>
        {post ? (
          <PaperDetail
            key={post.id}
            post={post}
            teamId={teamId}
            userId={userId}
            bookmarked={bookmarked}
            onClose={close}
          />
        ) : (
          <div className="p-10 text-center text-sm text-muted">
            {isLoading ? "Loading…" : "Paper not available."}
          </div>
        )}
      </Modal>
    </PaperModalContext.Provider>
  );
}
