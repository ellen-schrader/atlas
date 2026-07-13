import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BookMarked, Check, Loader2 } from "lucide-react";

import { BookmarkButton } from "@/components/BookmarkButton";
import { Cover } from "@/components/Cover";
import { usePaperModal } from "@/components/PaperModal";
import { useReadingList } from "@/hooks/useReadingList";
import { isWakingRecommendations, useRecommendations } from "@/hooks/useRecommendations";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

type Sort = "recommended" | "added";

interface Item {
  paperId: string;
  title: string;
  sub: string;
  similarity?: number;
}

/** The user's saved (to-read) papers, sortable by recommendation fit or date
 *  added. "Date added" is a pure Supabase read (works offline); "Recommended"
 *  ranks the same papers by the taste vector via the API. */
export default function ReadingList() {
  const { team, userId } = useAppContext();
  const { openPaper } = usePaperModal();
  const qc = useQueryClient();
  const [sort, setSort] = useState<Sort>("added");

  const byDate = useReadingList(userId, team.id);
  // Only fetch (and, during a cold boot, poll) the ranked view when it's shown.
  const byRec = useRecommendations(team.id, "reading_list", 100, sort === "recommended");
  const recWaking = isWakingRecommendations(byRec);

  const meta = (venue: string | null | undefined, year: number | null | undefined) =>
    [venue, year].filter(Boolean).join(" · ");

  const items: Item[] =
    sort === "added"
      ? (byDate.data ?? []).map((r) => ({
          paperId: r.paper_id,
          title: r.papers?.title ?? "Untitled paper",
          sub: meta(r.papers?.venue, r.papers?.year),
        }))
      : (byRec.data?.results ?? []).map((r) => ({
          paperId: r.post.papers.id,
          title: r.post.papers.title ?? "Untitled paper",
          sub: meta(r.post.papers.venue, r.post.papers.year),
          similarity: r.similarity,
        }));

  const loading = sort === "added" ? byDate.isLoading : byRec.isLoading;
  const recError = sort === "recommended" && byRec.isError;
  const empty = !loading && !recError && items.length === 0;

  async function markRead(paperId: string) {
    await supabase
      .from("paper_status")
      .upsert(
        { user_id: userId, team_id: team.id, paper_id: paperId, status: "read" },
        { onConflict: "user_id,paper_id,team_id" },
      );
    await qc.invalidateQueries({ queryKey: ["reading-list"] });
    await qc.invalidateQueries({ queryKey: ["recommendations"] });
    await qc.invalidateQueries({ queryKey: ["read-papers"] });
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-display font-serif font-semibold tracking-tight">Reading list</h1>
          <p className="mt-1.5 text-sm text-muted">Papers you saved to read in {team.name}.</p>
        </div>
        <div className="flex rounded-control border border-border bg-surface p-0.5 text-sm">
          {(["recommended", "added"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSort(s)}
              className={cn(
                "rounded-[7px] px-3 py-1.5 font-medium transition",
                sort === s ? "bg-accent-weak text-accent" : "text-muted hover:text-fg",
              )}
            >
              {s === "recommended" ? "Recommended" : "Date added"}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-16 text-muted">
          <Loader2 className="animate-spin" size={20} />
        </div>
      )}

      {recError && (
        <div className="rounded-card border border-dashed border-border bg-surface-2 p-5 text-sm">
          <p className="font-medium">
            {recWaking ? "Waking the paper service…" : "Couldn’t rank by recommendation right now."}
          </p>
          <p className="mt-1 text-xs text-muted">
            {recWaking ? (
              <>The ranking will appear here shortly, or </>
            ) : (
              <>The recommendation service isn’t reachable — </>
            )}
            <button onClick={() => setSort("added")} className="font-medium text-accent hover:underline">
              sort by date added
            </button>{" "}
            instead.
          </p>
        </div>
      )}

      {empty && (
        <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-border bg-surface-2 py-16 text-center">
          <BookMarked size={22} className="text-muted" />
          <p className="text-sm font-medium">Your reading list is empty</p>
          <p className="max-w-sm text-xs text-muted">
            Bookmark papers from the Papers page or a paper’s detail view and they’ll collect here.
          </p>
        </div>
      )}

      {!loading && !recError && items.length > 0 && (
        <div className="divide-y divide-border overflow-hidden rounded-card border border-border shadow-sm">
          {items.map((it) => (
            <div key={it.paperId} className="flex items-center gap-3.5 px-4 py-3 transition hover:bg-surface-2">
              <button onClick={() => openPaper(it.paperId)} className="flex min-w-0 flex-1 items-center gap-3.5 text-left">
                <span className="h-9 w-14 shrink-0 overflow-hidden rounded-md border border-border">
                  <Cover seed={it.paperId} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{it.title}</span>
                  <span className="mt-0.5 block truncate text-xs text-muted">{it.sub || "—"}</span>
                </span>
              </button>
              {it.similarity != null && it.similarity > 0 && (
                <span className="hidden shrink-0 text-xs tabular-nums text-muted sm:inline">
                  {Math.round(it.similarity * 100)}% match
                </span>
              )}
              <button
                onClick={() => markRead(it.paperId)}
                title="Mark as read"
                aria-label="Mark as read"
                className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-faint transition hover:bg-surface-3 hover:text-fg"
              >
                <Check size={15} />
              </button>
              <BookmarkButton
                paperId={it.paperId}
                teamId={team.id}
                userId={userId}
                bookmarked
                className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-accent hover:bg-surface-3"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
