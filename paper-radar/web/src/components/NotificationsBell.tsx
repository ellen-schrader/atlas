import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bell } from "lucide-react";

import { useMentionActions } from "@/hooks/useMentionActions";
import { useMentions } from "@/hooks/useMentions";
import { cn, formatDate, formatRelative } from "@/lib/utils";

/** Bell with an unread-mention count and a dropdown of unseen mentions. Opening
 *  one shows the paper (via the ?paper= route) and marks it seen. */
export function NotificationsBell({
  userId,
  align = "left",
  className,
}: {
  userId: string;
  align?: "left" | "right";
  className?: string;
}) {
  const { data: mentions } = useMentions(userId);
  const unseen = (mentions ?? []).filter((m) => !m.seen_at);
  const { markSeen, markAllSeen } = useMentionActions(userId);
  const [open, setOpen] = useState(false);
  const [, setSearchParams] = useSearchParams();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function openMention(paperId: string) {
    void markSeen(paperId);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("paper", paperId);
      return next;
    });
    setOpen(false);
  }

  return (
    <div className={cn("relative", className)} ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Notifications${unseen.length ? ` (${unseen.length} unread)` : ""}`}
        className="relative grid h-8 w-8 place-items-center rounded-control text-muted transition hover:bg-surface-2 hover:text-fg"
      >
        <Bell size={17} />
        {unseen.length > 0 && (
          <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-accent px-1 text-[10px] font-semibold tabular-nums text-accent-fg">
            {unseen.length > 9 ? "9+" : unseen.length}
          </span>
        )}
      </button>

      {open && (
        <div
          className={cn(
            "absolute top-full z-50 mt-2 w-80 overflow-hidden rounded-card border border-border bg-surface shadow-2xl",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
            <span className="text-sm font-semibold">Notifications</span>
            {unseen.length > 0 && (
              <button
                onClick={() => void markAllSeen()}
                className="text-xs font-medium text-muted transition hover:text-accent"
              >
                Mark all read
              </button>
            )}
          </div>
          {unseen.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-muted">You’re all caught up.</div>
          ) : (
            <div className="max-h-80 overflow-y-auto">
              {unseen.map((m) => (
                <button
                  key={m.id}
                  onClick={() => openMention(m.paper_id)}
                  className="flex w-full flex-col gap-0.5 border-b border-border px-3 py-2.5 text-left transition last:border-0 hover:bg-surface-2"
                >
                  <span className="text-eyebrow font-bold uppercase tracking-eyebrow text-accent">
                    Mentioned you
                  </span>
                  <span className="line-clamp-2 text-sm font-medium">{m.papers?.title ?? "A paper"}</span>
                  <span className="text-xs text-muted" title={formatDate(m.created_at)}>
                    {formatRelative(m.created_at)}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
