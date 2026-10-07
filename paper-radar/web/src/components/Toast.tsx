import { type ReactNode, createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

interface Toast {
  id: number;
  message: string;
  actionLabel?: string;
  /** Throw to report failure: the toast stays open, shows what went wrong, and
   *  keeps its button so the action can be tried again. */
  onAction?: () => void | Promise<void>;
  /** Milliseconds before it leaves on its own. */
  duration: number;
}

type Show = (t: Omit<Toast, "id" | "duration"> & { duration?: number }) => void;

const ToastContext = createContext<Show | null>(null);

/** Transient confirmation with an optional single action — an undo, mostly.
 *
 *  It lives above the router rather than inside a page, because the thing it
 *  confirms usually closes whatever was on screen: removing a paper shuts the
 *  dialog you removed it from, and an undo offered inside that dialog would
 *  leave with it. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(0);

  const show: Show = useCallback((t) => {
    const id = ++next.current;
    setToasts((all) => [...all, { duration: 8000, ...t, id }]);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((all) => all.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      {createPortal(
        <div
          // polite, not assertive: this reports something that already
          // happened and offers a way back, so it should not interrupt.
          role="status"
          aria-live="polite"
          // Rendered unconditionally, empty and all. A live region only
          // announces mutations to a region that was already in the DOM, so
          // inserting the region and its first message in the same commit is
          // silent — and the Undo it carries is the only route back from a
          // lab-wide removal.
          className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4"
        >
          {toasts.map((t) => (
            <ToastRow key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

function ToastRow({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Through a ref, so the countdown is armed once per toast. onDismiss is built
  // inline by the provider, so depending on it restarted the timer on every
  // ancestor render and a busy page could keep a toast up indefinitely.
  const dismissRef = useRef(onDismiss);
  dismissRef.current = onDismiss;
  useEffect(() => {
    timer.current = setTimeout(() => dismissRef.current(), toast.duration);
    return () => clearTimeout(timer.current);
  }, [toast.duration]);

  async function act() {
    if (!toast.onAction || busy) return;
    // Hold the toast open while the action runs: dismissing first would make a
    // failed undo look like it worked.
    clearTimeout(timer.current);
    setBusy(true);
    setFailed(null);
    try {
      await toast.onAction();
      onDismiss();
    } catch (e) {
      // Keep the toast — and its button — so the action can be retried. The
      // alternative, dismissing and reporting the failure in a second toast,
      // replaced the only Undo there was with a dead end: a removal cannot be
      // reached again from anywhere else in the app.
      setFailed(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className={cn(
        "pointer-events-auto flex max-w-md items-center gap-3 rounded-card border border-border",
        "bg-surface-2 px-3.5 py-2.5 shadow-[0_8px_24px_rgba(0,0,0,.45)]",
      )}
    >
      <span className="min-w-0 flex-1 text-sm text-fg">
        {toast.message}
        {failed && <span className="mt-0.5 block text-xs text-danger">{failed}</span>}
      </span>
      {toast.actionLabel && (
        <button
          type="button"
          onClick={act}
          disabled={busy}
          className={cn(
            "shrink-0 rounded-control px-2 py-1 text-sm font-semibold text-accent transition",
            "hover:bg-surface-3 disabled:opacity-60",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          )}
        >
          {busy ? "…" : failed ? "Try again" : toast.actionLabel}
        </button>
      )}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="shrink-0 rounded-control p-1 text-faint transition hover:text-fg"
      >
        <X size={14} />
      </button>
    </div>
  );
}

/** Returns a no-op outside the provider, so a component can always call it. */
export function useToast(): Show {
  return useContext(ToastContext) ?? (() => {});
}
