import { type ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/** Accessible modal dialog: portals to <body>, makes the app root `inert` while
 *  open (so focus and screen readers stay inside), locks body scroll, closes on
 *  Escape / backdrop, and restores focus to the trigger on close. */
export function Modal({
  open,
  onClose,
  children,
  label,
  className,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  label?: string;
  /** Override the dialog card's width (default `max-w-[660px]`). */
  className?: string;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const lastFocused = useRef<Element | null>(null);
  // Dismiss only when a press AND its release both land directly on the backdrop.
  // A drag that starts on the backdrop and ends inside the dialog (or the reverse
  // — selecting text in the dialog and releasing outside) must NOT close it, and a
  // `click` can't tell those apart because it fires on the common ancestor of the
  // two, which is the backdrop either way. Tracking pointerdown + pointerup can.
  const pressedBackdrop = useRef(false);

  // Keep the latest onClose in a ref so the setup effect below can depend on
  // `open` alone. Otherwise a parent that re-renders on each keystroke (e.g. a
  // dialog whose form state lives beside <Modal>) hands us a new onClose every
  // render, re-running the effect and stealing focus back to the close button.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    lastFocused.current = document.activeElement;
    const root = document.getElementById("root");
    if (root) root.inert = true;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const raf = requestAnimationFrame(() => closeRef.current?.focus());
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      cancelAnimationFrame(raf);
      if (root) root.inert = false;
      document.body.style.overflow = prevOverflow;
      if (lastFocused.current instanceof HTMLElement) lastFocused.current.focus();
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm sm:p-6"
      onPointerDown={(e) => {
        pressedBackdrop.current = e.target === e.currentTarget;
      }}
      onPointerUp={(e) => {
        if (e.target === e.currentTarget && pressedBackdrop.current) onClose();
        pressedBackdrop.current = false;
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className={cn(
          "relative flex max-h-[88vh] w-full flex-col overflow-hidden rounded-card border border-border bg-surface shadow-2xl",
          className ?? "max-w-[660px]",
        )}
      >
        <button
          ref={closeRef}
          onClick={onClose}
          aria-label="Close"
          className="absolute right-3 top-3 z-10 grid h-8 w-8 place-items-center rounded-control bg-black/40 text-white backdrop-blur-sm transition hover:bg-black/60"
        >
          <X size={16} />
        </button>
        {children}
      </div>
    </div>,
    document.body,
  );
}
