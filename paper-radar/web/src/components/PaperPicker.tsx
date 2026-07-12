import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

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

/** Search-and-pick one paper from the lab's collection, to link to a figure.
 *  Reuses the team-scoped `search_papers` RPC (same as the Papers page), which
 *  matches title, abstract, AND author names — so typing an author, or a word
 *  like "fibro", surfaces their papers. RLS scopes results to the lab. */
export function PaperPicker({
  teamId,
  value,
  onChange,
}: {
  teamId: string;
  value: PickedPaper | null;
  onChange: (paper: PickedPaper | null) => void;
}) {
  const [raw, setRaw] = useState("");
  const q = useDebouncedValue(raw.trim(), 250);

  const { data: results } = useQuery({
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
          .filter((x) => x !== null && x !== "" && x !== "—")
          .join(" · ");
        return { id: p.id, title: p.title ?? p.url, meta };
      });
    },
  });

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
    <div className="relative">
      <Input
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        placeholder="Search your lab's papers…"
      />
      {q.length > 0 && (results?.length ?? 0) > 0 && (
        <div className="mt-1.5 max-h-72 overflow-y-auto rounded-control border border-border bg-surface">
          {results!.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => onChange({ id: r.id, title: r.title })}
              className="block w-full border-b border-border px-3 py-2 text-left last:border-b-0 hover:bg-accent-weak"
            >
              <div className="truncate text-sm font-semibold text-fg">{r.title}</div>
              {r.meta && <div className="truncate text-xs text-muted">{r.meta}</div>}
            </button>
          ))}
        </div>
      )}
      {q.length > 0 && results && results.length === 0 && (
        <p className="mt-1.5 text-xs text-muted">No matching papers in your lab.</p>
      )}
    </div>
  );
}
