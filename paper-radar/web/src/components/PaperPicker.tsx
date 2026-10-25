import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";

import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { supabase } from "@/lib/supabase";
import type { PaperPost } from "@/lib/types";
import { formatAuthors } from "@/lib/utils";

export interface PickedPaper {
  id: string;
  title: string;
}

interface PaperResult extends PickedPaper {
  meta: string; // "A. Author, B. Author · Venue · 2025" — helps identify author matches
}

/** Search-and-pick one paper from the lab's collection (a figure's paper, a
 *  trial's or a collection's). With `value` it shows the pick as a chip; with
 *  `value={null}` and an `onChange` that saves, a click adds straight away.
 *  Reuses the team-scoped `search_papers` RPC (same as the Papers page), which
 *  matches title, abstract, AND author names — so typing an author, or a word
 *  like "fibro", surfaces their papers. RLS scopes results to the lab. */
export function PaperPicker({
  teamId,
  value,
  onChange,
  exclude,
  busy = false,
  autoFocus = false,
}: {
  teamId: string;
  value: PickedPaper | null;
  onChange: (paper: PickedPaper | null) => void;
  /** Papers already there (in the collection, linked to the trial): left out. */
  exclude?: readonly string[];
  /** The pick is being saved: results can't be clicked meanwhile. */
  busy?: boolean;
  autoFocus?: boolean;
}) {
  const [raw, setRaw] = useState("");
  const q = useDebouncedValue(raw.trim(), 250);

  const { data: found, isFetching } = useQuery({
    queryKey: ["paper-picker", teamId, q],
    enabled: value === null && q.length > 0,
    queryFn: async (): Promise<PaperResult[]> => {
      const { data, error } = await supabase
        .rpc("search_papers", { p_team: teamId, p_q: q, p_tag: null, p_limit: 8, p_offset: 0 })
        .select("papers(id, title, url, authors, venue, year)");
      if (error) throw error;
      return ((data ?? []) as unknown as PaperPost[]).map((post) => {
        const p = post.papers;
        const meta = [formatAuthors(p.authors, 2), p.venue, p.year]
          .filter((x) => x !== null && x !== "" && x !== "–")
          .join(" · ");
        return { id: p.id, title: p.title ?? p.url, meta };
      });
    },
  });
  const results = found?.filter((r) => !exclude?.includes(r.id));

  if (value) {
    return (
      <div className="flex items-center gap-2">
        <span className="inline-flex max-w-full items-center gap-2 rounded-chip border border-accent bg-accent-weak px-2.5 py-1.5 text-sm font-medium text-accent">
          <span className="truncate">{value.title}</span>
          <button
            type="button"
            aria-label="Unlink paper"
            onClick={() => {
              onChange(null);
              setRaw("");
            }}
            className="shrink-0 text-accent/70 hover:text-danger"
          >
            <X size={14} />
          </button>
        </span>
      </div>
    );
  }

  return (
    // min-w-0: long titles wrap inside the picker instead of widening its column.
    <div className="relative min-w-0">
      <Input
        autoFocus={autoFocus}
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        placeholder="Search your lab’s papers by title, author or words…"
        aria-label="Search your lab’s papers"
      />
      {raw.trim() && (isFetching || raw.trim() !== q) && (
        <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted">
          <Loader2 size={12} className="animate-spin" aria-hidden /> Searching…
        </p>
      )}
      {q.length > 0 && !isFetching && (results?.length ?? 0) > 0 && (
        <ul className="mt-1.5 max-h-72 overflow-y-auto rounded-control border border-border bg-surface">
          {results!.map((r) => (
            <li key={r.id} className="border-b border-border last:border-b-0">
              <button
                type="button"
                disabled={busy}
                onClick={() => onChange({ id: r.id, title: r.title })}
                className="block w-full px-3 py-2 text-left hover:bg-accent-weak focus-visible:bg-accent-weak focus-visible:outline-none disabled:cursor-wait disabled:opacity-60"
              >
                <div className="line-clamp-2 text-sm font-semibold text-fg">{r.title}</div>
                {r.meta && <div className="truncate text-xs text-muted">{r.meta}</div>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {q.length > 0 && !isFetching && results && results.length === 0 && (
        <p className="mt-1.5 text-xs text-muted">
          {found?.length ? "Those papers are already here." : "No matching papers in your lab."}
        </p>
      )}
    </div>
  );
}
