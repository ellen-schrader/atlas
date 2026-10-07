import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { PaperDetail } from "@/components/PaperDetail";
import { Button } from "@/components/ui/button";
import { useReadingList } from "@/hooks/useReadingList";
import { supabase } from "@/lib/supabase";
import type { PaperPost } from "@/lib/types";
import { useAppContext } from "@/routes/Layout";

/**
 * A paper on its own page — a stable /papers/:id URL for deep reading and
 * sharing, rather than only the ?paper= modal overlay. Renders PaperDetail in its
 * `fullPage` mode, which drops the dialog's inner scroll area so the paper is one
 * continuous column instead of a pane within a pane.
 *
 * Note it is NOT the document that scrolls: the shell clamps itself to
 * `md:h-screen md:overflow-hidden` and makes <main> the scroll container
 * (routes/Layout.tsx), so on desktop this moves the scrollbar one level out, not
 * all the way to the page. Printing is still bounded by <main>.
 */
export default function PaperPage() {
  const { paperId } = useParams();
  const { team, userId } = useAppContext();
  const navigate = useNavigate();
  const location = useLocation();
  // Same source the modal uses, so the bookmark state matches whichever way
  // the paper was opened.
  const { data: reading } = useReadingList(userId, team.id);

  // The shell's <main> is the scroll container and is not remounted on a sibling
  // route change, so arriving from deep in an infinite-scrolled Papers list opens
  // this page already scrolled past the title and the Read/Cite buttons. There is
  // no ScrollRestoration in the app, so do it here.
  //
  // Both, because which element scrolls depends on the viewport: Layout clamps
  // the height and hides overflow only at md and up. Below that the column grows
  // to its content, <main> never overflows, and the document is the scroller — so
  // scrolling <main> alone was a no-op on exactly the phones this matters most on.
  useEffect(() => {
    document.querySelector("main")?.scrollTo({ top: 0 });
    window.scrollTo({ top: 0 });
  }, [paperId]);

  const { data: post, isLoading, isError, refetch } = useQuery({
    queryKey: ["paper-post", team.id, paperId],
    enabled: !!paperId,
    queryFn: async (): Promise<PaperPost | null> => {
      const { data, error } = await supabase
        .from("paper_posts")
        .select(
          "id, posted_at, note, posted_by, posted_by_label, source, tags, papers(*), poster:profiles!paper_posts_posted_by_fkey(display_name)",
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
        // A deep link opened in a fresh tab has nothing to pop — react-router
        // marks that first entry with key "default" — so fall back to the list
        // rather than leaving Back inert or walking the user out of Atlas.
        onClick={() => (location.key === "default" ? navigate("/papers") : navigate(-1))}
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted transition hover:text-fg"
      >
        <ChevronLeft size={16} /> Back
      </button>

      <div className="overflow-hidden rounded-card border border-border bg-surface shadow-sm">
        {post ? (
          <PaperDetail
            // Remount per paper. React Router keeps this component mounted across
            // a :paperId change, and PaperDetail holds per-paper state seeded from
            // props (PaperTags' tag list above all). Without a key, navigating to
            // an already-cached paper never re-runs that state and the previous
            // paper's tags get written onto this one's post.
            key={post.id}
            post={post}
            teamId={team.id}
            teamName={team.name}
            userId={userId}
            bookmarked={(reading ?? []).some((r) => r.paper_id === post.papers.id)}
            fullPage
            // The delete control lives in PaperDetail and calls this when the post
            // is gone. On the modal path it closes the dialog; here there is no
            // dialog, so leave the route — the page it describes no longer exists.
            onClose={() => navigate("/papers", { replace: true })}
          />
        ) : isError ? (
          // Distinct from the not-in-your-lab case below: a failed fetch must not
          // be reported as an access answer we never actually got.
          <div className="flex flex-col items-center gap-3 p-12 text-center">
            <p className="text-sm text-muted">Couldn’t load this paper.</p>
            <Button variant="secondary" size="sm" onClick={() => void refetch()}>
              Retry
            </Button>
          </div>
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
