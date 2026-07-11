import { PaperEngagement } from "@/components/Engagement";
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
  const tags = [...new Set([...p.tags, ...p.keywords])];
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
      {tags.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {tags.map((t) => (
            <span
              key={t}
              className="rounded-full border border-border px-2 py-0.5 font-mono text-xs text-muted"
            >
              {t}
            </span>
          ))}
        </div>
      )}
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
