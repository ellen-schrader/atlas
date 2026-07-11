import { type FormEvent, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { PaperEngagement } from "@/components/Engagement";
import { supabase } from "@/lib/supabase";
import type { PaperPost } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export function PaperDetail({
  post,
  teamId,
  userId,
}: {
  post: PaperPost;
  teamId: string;
  userId: string;
}) {
  const p = post.papers;
  const canonical = [...new Set([...p.tags, ...p.keywords])];
  return (
    <div className="p-6">
      <h2 className="pr-8 text-base font-semibold">{p.title ?? p.url}</h2>
      {[p.venue, p.year, p.doi].some(Boolean) && (
        <div className="mt-1 font-mono text-xs text-muted">
          {[p.venue, p.year, p.doi].filter(Boolean).join(" · ")}
        </div>
      )}
      {p.authors.length > 0 && <div className="mt-2 text-sm text-muted">{p.authors.join(", ")}</div>}
      {p.abstract ? (
        <p className="mt-4 text-sm leading-relaxed">{p.abstract}</p>
      ) : (
        <p className="mt-4 text-sm italic text-muted">No abstract available.</p>
      )}
      <PaperTags postId={post.id} teamId={teamId} initial={post.tags} canonical={canonical} />
      <div className="mt-5 flex flex-wrap gap-4 text-sm">
        <a href={p.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
          Paper ↗
        </a>
        {p.code_url && (
          <a href={p.code_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
            Code ↗
          </a>
        )}
        {p.data_url && (
          <a href={p.data_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
            Data ↗
          </a>
        )}
      </div>
      <div className="mt-5 border-t border-border pt-3 font-mono text-xs text-muted">
        Posted {formatDate(post.posted_at)}
        {post.posted_by_label ? ` · ${post.posted_by_label}` : ""}
        {post.note && <div className="mt-1">“{post.note}”</div>}
      </div>

      <PaperEngagement paperId={p.id} teamId={teamId} userId={userId} />
    </div>
  );
}

function PaperTags({
  postId,
  teamId,
  initial,
  canonical,
}: {
  postId: string;
  teamId: string;
  initial: string[];
  canonical: string[];
}) {
  const qc = useQueryClient();
  const [tags, setTags] = useState<string[]>(initial);
  const [input, setInput] = useState("");

  async function persist(next: string[]) {
    setTags(next);
    await supabase.from("paper_posts").update({ tags: next }).eq("id", postId);
    qc.invalidateQueries({ queryKey: ["papers", teamId] });
    qc.invalidateQueries({ queryKey: ["paper-post"] });
  }

  function add(e: FormEvent) {
    e.preventDefault();
    const t = input.trim().toLowerCase();
    setInput("");
    if (t && !tags.includes(t)) void persist([...tags, t]);
  }

  return (
    <div className="mt-4">
      <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Tags</div>
      <div className="flex flex-wrap items-center gap-1.5">
        {tags.map((t) => (
          <span
            key={t}
            className="flex items-center gap-1 rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 font-mono text-xs text-accent"
          >
            {t}
            <button
              type="button"
              aria-label={`Remove ${t}`}
              onClick={() => void persist(tags.filter((x) => x !== t))}
              className="hover:text-danger"
            >
              ×
            </button>
          </span>
        ))}
        {canonical
          .filter((t) => !tags.includes(t))
          .map((t) => (
            <span
              key={t}
              className="rounded-full border border-border px-2 py-0.5 font-mono text-xs text-muted"
            >
              {t}
            </span>
          ))}
        <form onSubmit={add}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="+ tag"
            className="w-20 rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-xs placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </form>
      </div>
    </div>
  );
}
