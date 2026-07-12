import { useState } from "react";

import { Avatar } from "@/components/Avatar";
import { EngagementSummary } from "@/components/EngagementSummary";
import { aspectRatio, categoryLabel } from "@/lib/figures";
import type { Figure } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";

/** A single figure in the masonry board: the image at its natural aspect ratio
 *  (so layout is stable before load), a category badge, and a footer with the
 *  same engagement summary as paper cards. Opens the detail modal on click. */
export function FigureCard({
  figure,
  url,
  reactions = 0,
  comments = 0,
  onOpen,
}: {
  figure: Figure;
  url?: string;
  reactions?: number;
  comments?: number;
  onOpen: () => void;
}) {
  const [loaded, setLoaded] = useState(false);
  const uploaderName = figure.uploader?.display_name ?? null;

  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className={cn(
        "group mb-4 flex break-inside-avoid cursor-pointer flex-col overflow-hidden rounded-card border border-border bg-surface shadow-sm transition",
        "hover:-translate-y-0.5 hover:border-border-strong",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
      )}
    >
      <div className="relative w-full bg-surface-2" style={{ aspectRatio: aspectRatio(figure) }}>
        {url && (
          <img
            src={url}
            alt={figure.title || figure.caption || "Figure"}
            loading="lazy"
            onLoad={() => setLoaded(true)}
            className={cn(
              "h-full w-full object-cover transition-opacity duration-200",
              loaded ? "opacity-100" : "opacity-0",
            )}
          />
        )}
        {figure.category.trim() && (
          <span className="absolute left-2.5 top-2.5 rounded-full border border-border bg-surface/80 px-2 py-0.5 text-eyebrow font-semibold uppercase tracking-eyebrow text-fg backdrop-blur">
            {categoryLabel(figure.category)}
          </span>
        )}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/45 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
      <div className="flex flex-col gap-2.5 p-4">
        {figure.title && (
          <h3 className="text-card font-semibold tracking-snug text-fg">{figure.title}</h3>
        )}
        {figure.papers?.title && (
          <span className="text-meta inline-flex max-w-full items-center gap-1.5 text-muted">
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="shrink-0 text-accent"
            >
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
            <span className="truncate">{figure.papers.title}</span>
          </span>
        )}
        <div className="mt-1 flex items-center justify-between gap-3 border-t border-border pt-3">
          <EngagementSummary reactions={reactions} comments={comments} />
          <span className="text-meta inline-flex items-center gap-2 text-muted">
            {uploaderName && <Avatar name={uploaderName} size={20} />}
            <span className="tabular-nums">{formatDate(figure.created_at)}</span>
          </span>
        </div>
      </div>
    </article>
  );
}
