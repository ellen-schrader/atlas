import { type RefObject, useEffect, useRef } from "react";

/**
 * Close a popover when the user clicks outside it or presses Escape.
 *
 * Both listeners run in the **capture** phase and stop the event, which is the
 * part that is easy to get wrong: a popover opened inside `ui/modal.tsx` shares
 * `document` with the Modal's own Escape handler and sits over its backdrop,
 * which dismisses on a pointerdown/pointerup pair. Without capturing, one press
 * of Escape or one click on the backdrop closes the popover *and* the dialog
 * behind it — the inner layer has to win, and a second press then closes the
 * dialog as normal.
 *
 * pointerdown rather than mousedown for the same reason: pointer events fire
 * first, so taking the pointerdown leaves the Modal's pair unarmed.
 *
 * `onDismiss` is told which it was. Returning focus to the trigger is right for
 * Escape — the keyboard user is otherwise dropped at the top of the document —
 * and wrong for a click, which lands the focus ring somewhere the user did not
 * put it; on a destructive trigger, the next Space reopens it.
 *
 * Replaces four hand-rolled copies of this effect (ExportBar, NotificationsBell,
 * PaperDetail, Papers), only one of which handled the layering.
 */
export function useDismissable(
  ref: RefObject<HTMLElement | null>,
  open: boolean,
  onDismiss: (reason: "escape" | "outside") => void,
): void {
  // Through a ref, so the listeners always see the current callback while the
  // effect still depends on `open` alone. Re-running it on every parent render
  // would be wasteful; capturing the first callback forever is worse — a
  // handler that reads state (say, "is a write in flight?") would go on reading
  // the value it had when the popover opened.
  const cb = useRef(onDismiss);
  cb.current = onDismiss;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (ref.current?.contains(e.target as Node)) return;
      e.stopPropagation();
      cb.current("outside");
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      cb.current("escape");
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open, ref]);
}
