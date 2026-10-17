import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bell } from "lucide-react";

import { useDismissable } from "@/hooks/useDismissable";
import { useMentionActions } from "@/hooks/useMentionActions";
import { useMentions } from "@/hooks/useMentions";
import { usePaperNoticeActions, usePaperNotices } from "@/hooks/usePaperNotices";
import { cn, formatDate, formatRelative } from "@/lib/utils";

/** One row in the bell: an @-mention, or a preprint that has been published. */
interface Unseen {
  key: string;
  kind: "mention" | "published";
  paperId: string;
  createdAt: string;
  title: string;
  /** For "published": where, e.g. "Nature · 2026". */
  detail?: string;
  /** What to mark seen: the mention's paper, or the notice's id. */
  seenId: string;
}

/** Everything unseen, newest first: for the bell and for the collapsed bar's
 *  avatar dot. */
export function useUnseenNotifications(userId: string): Unseen[] {
  const { data: mentions } = useMentions(userId);
  const { data: notices } = usePaperNotices(userId);
  const items: Unseen[] = [
    ...(mentions ?? [])
      .filter((m) => !m.seen_at)
      .map((m) => ({
        key: `m-${m.id}`,
        kind: "mention" as const,
        paperId: m.paper_id,
        createdAt: m.created_at,
        title: m.papers?.title ?? "A paper",
        seenId: m.paper_id,
      })),
    ...(notices ?? [])
      .filter((n) => !n.seen_at)
      .map((n) => ({
        key: `n-${n.id}`,
        kind: "published" as const,
        paperId: n.paper_id,
        createdAt: n.created_at,
        title: n.payload.title ?? "A preprint",
        detail: [n.payload.venue, n.payload.year].filter(Boolean).join(" · ") || undefined,
        seenId: n.id,
      })),
  ];
  return items.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

/** "Mark all read" and everything unseen. Opening one shows the paper (via the
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
  const unseen = useUnseenNotifications(userId);
  const mentions = useMentionActions(userId);
  const notices = usePaperNoticeActions(userId);
  const [, setSearchParams] = useSearchParams();
  const role = inMenu ? "menuitem" : undefined;

  function markAllSeen() {
    return Promise.all([mentions.markAllSeen(), notices.markAllSeen()]);
  }

  function open(item: Unseen) {
    const paperId = item.paperId;
    void (item.kind === "mention" ? mentions.markSeen(item.seenId) : notices.markSeen(item.seenId));
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
              key={m.key}
              role={role}
              onClick={() => open(m)}
              className="flex w-full flex-col gap-0.5 border-b border-border px-3 py-2.5 text-left transition last:border-0 hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none"
            >
              <span className="text-eyebrow font-bold uppercase tracking-eyebrow text-accent">
                {m.kind === "mention" ? "Mentioned you" : "Preprint published"}
              </span>
              <span className="line-clamp-2 text-sm font-medium">{m.title}</span>
              {m.detail && <span className="text-xs text-muted">Now in {m.detail}</span>}
              <span className="text-xs text-muted" title={formatDate(m.createdAt)}>
                {formatRelative(m.createdAt)}
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}

/** Bell with an unread dot and a dropdown of unseen mentions and notices. */
export function NotificationsBell({
  userId,
  align = "left",
  className,
}: {
  userId: string;
  align?: "left" | "right";
  className?: string;
}) {
  const unseen = useUnseenNotifications(userId);
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
