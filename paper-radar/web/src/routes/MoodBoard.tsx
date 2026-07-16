import { useEffect, useMemo, useRef, useState } from "react";
import { ImagePlus, Loader2 } from "lucide-react";

import { FigureCard } from "@/components/FigureCard";
import { FigureUploadDialog } from "@/components/FigureUploadDialog";
import { useFigureModal } from "@/components/FigureModal";
import { Button } from "@/components/ui/button";
import {
  useFigureCategories,
  useFigureEngagementCounts,
  useFigureUrls,
  useFigures,
} from "@/hooks/useFigures";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

const LINKED = "__linked__";

export default function MoodBoard() {
  const { team, userId } = useAppContext();
  const [filter, setFilter] = useState<string | null>(null); // category value, LINKED, or null (all)
  const [uploadOpen, setUploadOpen] = useState(false);

  const figuresQuery = useFigures(team.id, {
    category: filter && filter !== LINKED ? filter : null,
    linkedOnly: filter === LINKED,
  });
  const figures = useMemo(() => (figuresQuery.data?.pages ?? []).flat(), [figuresQuery.data]);

  const { data: urls } = useFigureUrls(figures.map((f) => f.storage_path));
  const { data: counts } = useFigureEngagementCounts(
    team.id,
    figures.map((f) => f.id),
  );
  const { data: labCategories } = useFigureCategories(team.id);

  const { openFigure } = useFigureModal();

  // Infinite scroll: fetch the next page when the sentinel scrolls into view.
  // Depend on the specific query fields (not the whole query object, whose
  // identity changes every render) so the observer isn't torn down each render.
  const { fetchNextPage, hasNextPage, isFetchingNextPage } = figuresQuery;
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
        void fetchNextPage();
      }
    });
    io.observe(el);
    return () => io.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  const chips: { key: string; label: string; value: string | null }[] = [
    { key: "all", label: "All", value: null },
    ...(labCategories ?? []).map((c) => ({ key: c.category, label: c.category, value: c.category })),
    { key: LINKED, label: "Linked to paper", value: LINKED },
  ];

  const loading = figuresQuery.isLoading;
  const empty = !loading && figures.length === 0;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-display font-serif font-semibold tracking-tight text-fg">Your lab’s look</h1>
          <p className="mt-1.5 max-w-[52ch] text-sm text-muted">
            Figures your lab admires — your own and others’. Atlas derives your palette from them,
            and hands Claude a matplotlib style sheet so it plots in your lab’s style.
          </p>
        </div>
        <Button onClick={() => setUploadOpen(true)}>
          <ImagePlus size={16} /> Upload figure
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        {chips.map((c) => {
          const on = filter === c.value;
          return (
            <button
              key={c.key}
              type="button"
              onClick={() => setFilter(c.value)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-sm transition",
                on
                  ? "border-accent bg-accent-weak text-accent"
                  : "border-border bg-surface text-muted hover:border-accent hover:text-fg",
              )}
            >
              {c.label}
            </button>
          );
        })}
      </div>

      {loading && (
        <div className="flex items-center justify-center py-20 text-muted">
          <Loader2 className="animate-spin" size={20} />
        </div>
      )}

      {empty && (
        <div className="flex flex-col items-center gap-3 rounded-card border border-dashed border-border bg-surface-2 py-16 text-center">
          <p className="text-sm text-muted">
            {filter
              ? "No figures match this filter yet."
              : "No figures yet. Add ones you admire — your own or others’ — and Atlas learns your lab’s palette from them."}
          </p>
          {!filter && (
            <Button variant="secondary" onClick={() => setUploadOpen(true)}>
              <ImagePlus size={16} /> Add the first figure
            </Button>
          )}
        </div>
      )}

      {!loading && figures.length > 0 && (
        <div className="gap-4 [column-fill:_balance] columns-1 sm:columns-2 lg:columns-3 xl:columns-4">
          {figures.map((f) => (
            <FigureCard
              key={f.id}
              figure={f}
              url={urls?.[f.storage_path]}
              reactions={counts?.[f.id]?.reactions ?? 0}
              comments={counts?.[f.id]?.comments ?? 0}
              onOpen={() => openFigure(f.id)}
            />
          ))}
        </div>
      )}

      <div ref={sentinel} className="h-8" />
      {figuresQuery.isFetchingNextPage && (
        <div className="flex justify-center py-2 text-muted">
          <Loader2 className="animate-spin" size={18} />
        </div>
      )}

      <FigureUploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        teamId={team.id}
        userId={userId}
      />
    </div>
  );
}
