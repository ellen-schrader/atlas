import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bell } from "lucide-react";

import { useDismissable } from "@/hooks/useDismissable";
import { useMentionActions } from "@/hooks/useMentionActions";
import { useMentions } from "@/hooks/useMentions";
import { cn, formatDate, formatRelative } from "@/lib/utils";

/** Unseen mentions, for the bell and for the collapsed bar's avatar dot. */
export function useUnseenMentions(userId: string) {
  const { data: mentions } = useMentions(userId);
  return (mentions ?? []).filter((m) => !m.seen_at);
}

/** "Mark all read" and the unseen mentions. Opening one shows the paper (via the
 *  ?paper= route) and marks it seen. `inMenu` makes the rows menu items, for the
 *  copy that lives inside the profile menu. */
export function NotificationsList({
  userId,
  onOpened,
  onMarkedAll,
  inMenu = false,
}: {
  userId: string;
  onOpened: () => void;
  onMarkedAll?: () => void;
  inMenu?: boolean;
}) {
  const unseen = useUnseenMentions(userId);
  const { markSeen, markAllSeen } = useMentionActions(userId);
  const [, setSearchParams] = useSearchParams();
  const role = inMenu ? "menuitem" : undefined;

  function openMention(paperId: string) {
    void markSeen(paperId);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("paper", paperId);
      return next;
    });
    onOpened();
  }

  return (
    <>
      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <span className="text-sm font-semibold">Notifications</span>
        {unseen.length > 0 && (
          <button
            role={role}
            onClick={() => {
              void markAllSeen();
              onMarkedAll?.();
            }}
            className="rounded text-xs font-medium text-muted transition hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
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
              role={role}
              onClick={() => openMention(m.paper_id)}
              className="flex w-full flex-col gap-0.5 border-b border-border px-3 py-2.5 text-left transition last:border-0 hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none"
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
    </>
  );
}

/** Bell with an unread dot and a dropdown of unseen mentions. */
export function NotificationsBell({
  userId,
  align = "left",
  className,
}: {
  userId: string;
  align?: "left" | "right";
  className?: string;
}) {
  const unseen = useUnseenMentions(userId);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);

  // Fixed, from the button's own position: the sidebar and the collapsed bar
  // scroll (overflow-y: auto), which clips anything absolutely positioned
  // inside them — a 320px panel in a 68px bar was cut to its first few letters.
  function toggle() {
    if (open) return setOpen(false);
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    const width = Math.min(320, window.innerWidth - 16);
    const wanted = align === "right" ? rect.right - width : rect.left;
    const left = Math.max(8, Math.min(wanted, window.innerWidth - width - 8));
    setPos({ top: rect.bottom + 8, left, width });
    setOpen(true);
  }

  // Capture-phase, so over a dialog or inside the mobile drawer one Escape or
  // outside click closes this and nothing behind it.
  useDismissable(ref, open, (reason) => {
    setOpen(false);
    if (reason === "escape") buttonRef.current?.focus();
  });

  // A fixed panel would be left hanging where the button used to be.
  useEffect(() => {
    if (!open) return;
    const onResize = () => setOpen(false);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open]);

  return (
    <div className={cn("relative", className)} ref={ref}>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggle}
        aria-label={`Notifications${unseen.length ? `, ${unseen.length} unread` : ""}`}
        aria-haspopup="true"
        aria-expanded={open}
        className="relative grid h-8 w-8 place-items-center rounded-lg text-muted transition hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <Bell size={16} />
        {/* A dot, not a count: the sidebar's one cyan is "you are here", and a
            number there competed with it. The count is in the label. */}
        {unseen.length > 0 && (
          <span
            aria-hidden
            className="absolute right-1.5 top-1.5 h-[7px] w-[7px] rounded-full bg-accent ring-2 ring-surface"
          />
        )}
      </button>

      {open && pos && (
        <div
          style={{ top: pos.top, left: pos.left, width: pos.width }}
          className="fixed z-50 overflow-hidden rounded-card border border-border bg-surface shadow-2xl"
        >
          <NotificationsList
            userId={userId}
            onOpened={() => setOpen(false)}
            onMarkedAll={() => buttonRef.current?.focus()}
          />
        </div>
      )}
    </div>
  );
}
