import { type RefObject, useEffect } from "react";

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
 * Replaces four hand-rolled copies of this effect (ExportBar, NotificationsBell,
 * PaperDetail, Papers), only one of which handled the layering.
 */
export function useDismissable(
  ref: RefObject<HTMLElement | null>,
  open: boolean,
  onDismiss: () => void,
): void {
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (ref.current?.contains(e.target as Node)) return;
      e.stopPropagation();
      onDismiss();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onDismiss();
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey, true);
    };
    // onDismiss is a setter in every call site; including it would re-run the
    // effect on each render of the parent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ref]);
}
