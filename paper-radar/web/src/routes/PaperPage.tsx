import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import { PaperDetail } from "@/components/PaperDetail";
import { useReadingList } from "@/hooks/useReadingList";
import { supabase } from "@/lib/supabase";
import type { PaperPost } from "@/lib/types";
import { useAppContext } from "@/routes/Layout";

/**
 * A paper on its own page — a stable /papers/:id URL for deep reading, printing,
 * and sharing, rather than only the ?paper= modal overlay. Renders PaperDetail in
 * its flow-not-scroll `fullPage` mode, so the browser owns the scrollbar and the
 * whole paper prints instead of just the visible slice of a dialog.
 */
export default function PaperPage() {
  const { paperId } = useParams();
  const { team, userId } = useAppContext();
  const navigate = useNavigate();
  // Same source the modal uses, so the bookmark state matches whichever way
  // the paper was opened.
  const { data: reading } = useReadingList(userId, team.id);

  const { data: post, isLoading } = useQuery({
    queryKey: ["paper-post", team.id, paperId],
    enabled: !!paperId,
    queryFn: async (): Promise<PaperPost | null> => {
      const { data, error } = await supabase
        .from("paper_posts")
        .select(
          "id, posted_at, note, posted_by, posted_by_label, tags, papers(*), poster:profiles!paper_posts_posted_by_fkey(display_name)",
        )
        .eq("team_id", team.id)
        .eq("paper_id", paperId!)
        .maybeSingle();
      if (error) throw error;
      return (data as unknown as PaperPost) ?? null;
    },
  });

  return (
    <div className="mx-auto max-w-3xl p-6 md:p-8">
      <button
        type="button"
        onClick={() => navigate(-1)}
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted transition hover:text-fg"
      >
        <ChevronLeft size={16} /> Back
      </button>

      <div className="overflow-hidden rounded-card border border-border bg-surface shadow-sm">
        {post ? (
          <PaperDetail
            post={post}
            teamId={team.id}
            userId={userId}
            bookmarked={(reading ?? []).some((r) => r.paper_id === post.papers.id)}
            fullPage
          />
        ) : (
          // RLS scopes paper_posts to the caller's labs, so a miss is either a
          // paper another lab posted or one that has been deleted — not an error.
          <div className="p-12 text-center text-sm text-muted">
            {isLoading ? "Loading…" : "This paper isn’t in your lab."}
          </div>
        )}
      </div>
    </div>
  );
}
