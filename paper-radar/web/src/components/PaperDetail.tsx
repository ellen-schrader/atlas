import { type FormEvent, type ReactNode, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { BookmarkButton } from "@/components/BookmarkButton";
import { Cover } from "@/components/Cover";
import { PaperEngagement } from "@/components/Engagement";
import { supabase } from "@/lib/supabase";
import type { PaperPost } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export function PaperDetail({
  post,
  teamId,
  userId,
  bookmarked = false,
}: {
  post: PaperPost;
  teamId: string;
  userId: string;
  bookmarked?: boolean;
}) {
  const p = post.papers;
  const canonical = [...new Set([...p.tags, ...p.keywords])];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative h-[150px] shrink-0">
        <Cover seed={p.id} />
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-4">
          {[p.venue, p.year].filter(Boolean).length > 0 && (
            <span className="text-eyebrow font-semibold uppercase tracking-eyebrow tabular-nums text-white/90">
              {[p.venue, p.year].filter(Boolean).join(" · ")}
            </span>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        <h2 className="text-balance text-[21px] font-bold leading-tight tracking-tight">
          {p.title ?? p.url}
        </h2>
        {p.authors.length > 0 && <div className="mt-2.5 text-sm text-muted">{p.authors.join(", ")}</div>}
        <div className="mt-1 break-all font-mono text-xs text-faint">{p.doi ?? p.url}</div>

        <div className="mt-4 flex flex-wrap gap-2">
          <a
            href={p.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-control bg-accent px-3 py-2 text-sm font-semibold text-accent-fg transition hover:brightness-110"
          >
            Read paper <ExternalLink size={13} />
          </a>
          {p.code_url && <LinkBtn href={p.code_url}>Code</LinkBtn>}
          {p.data_url && <LinkBtn href={p.data_url}>Data</LinkBtn>}
          <BookmarkButton
            paperId={p.id}
            teamId={teamId}
            userId={userId}
            bookmarked={bookmarked}
            showLabel
            className="rounded-control border border-border px-3 py-2 text-sm font-medium hover:border-accent hover:text-accent aria-pressed:border-accent aria-pressed:text-accent"
          />
        </div>

        <MetaLabel>Abstract</MetaLabel>
        {p.abstract ? (
          <p className="text-sm leading-relaxed text-fg/90">{p.abstract}</p>
        ) : (
          <p className="text-sm italic text-muted">No abstract available.</p>
        )}

        <MetaLabel>Tags</MetaLabel>
        <PaperTags postId={post.id} teamId={teamId} initial={post.tags} canonical={canonical} />

        <div className="mt-5 flex items-center gap-2 text-xs text-muted">
          {post.posted_by_label && <Avatar name={post.posted_by_label} size={22} />}
          <span>
            Posted {post.posted_by_label ? `by ${post.posted_by_label} ` : ""}· {formatDate(post.posted_at)}
          </span>
        </div>
        {post.note && (
          <div className="mt-2 rounded-md border border-border bg-surface-2 p-2.5 text-sm text-muted">
            “{post.note}”
          </div>
        )}

        <hr className="my-6 border-border" />
        <MetaLabel>Discussion</MetaLabel>
        <PaperEngagement paperId={p.id} teamId={teamId} userId={userId} />
      </div>
    </div>
  );
}

function MetaLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-2 mt-5 text-eyebrow font-bold uppercase tracking-eyebrow text-muted">{children}</div>
  );
}

function LinkBtn({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-2 text-sm font-medium transition hover:border-accent hover:text-accent"
    >
      {children} <ExternalLink size={13} />
    </a>
  );
}

/** Lab-scoped, editable tags on the post. Canonical (paper/keyword) tags render
 *  as dashed chips you can click to add. */
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
    void qc.invalidateQueries({ queryKey: ["paper-search", teamId] });
    void qc.invalidateQueries({ queryKey: ["team-tags", teamId] });
    void qc.invalidateQueries({ queryKey: ["paper-post"] });
  }

  function add(e: FormEvent) {
    e.preventDefault();
    const t = input.trim().toLowerCase();
    setInput("");
    if (t && !tags.includes(t)) void persist([...tags, t]);
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tags.map((t) => (
        <span
          key={t}
          className="inline-flex items-center gap-1 rounded-chip border border-accent/40 bg-accent-weak px-2 py-0.5 font-mono text-xs text-accent"
        >
          {t}
          <button
            type="button"
            aria-label={`Remove ${t}`}
            onClick={() => void persist(tags.filter((x) => x !== t))}
            className="text-accent/70 hover:text-danger"
          >
            ×
          </button>
        </span>
      ))}
      {canonical
        .filter((t) => !tags.includes(t))
        .map((t) => (
          <button
            key={t}
            type="button"
            title="Add tag"
            onClick={() => void persist([...tags, t])}
            className="rounded-chip border border-dashed border-border px-2 py-0.5 font-mono text-xs text-faint transition hover:border-accent hover:text-accent"
          >
            {t}
          </button>
        ))}
      <form onSubmit={add}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="+ tag"
          className="w-20 rounded-chip border border-border bg-surface px-2 py-0.5 font-mono text-xs placeholder:text-faint focus:outline-none focus:ring-1 focus:ring-accent"
        />
      </form>
    </div>
  );
}
