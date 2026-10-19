import { useCallback, useEffect, useRef, useState } from "react";

/** The item someone just added, for a few seconds: its row shows "Added" and
 *  scrolls into view, so the change is seen where it happened (a toast at the
 *  bottom of the screen was easy to miss). */
export function useJustAdded(ms = 4000): {
  justAdded: string | null;
  markAdded: (id: string) => void;
  /** Attach to the row: scrolls it into view the first time it renders as new. */
  rowRef: (id: string) => (el: HTMLElement | null) => void;
} {
  const [justAdded, setJustAdded] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const scrolled = useRef<string | null>(null);

  const markAdded = useCallback(
    (id: string) => {
      clearTimeout(timer.current);
      scrolled.current = null;
      setJustAdded(id);
      timer.current = setTimeout(() => setJustAdded(null), ms);
    },
    [ms],
  );
  useEffect(() => () => clearTimeout(timer.current), []);

  const rowRef = useCallback(
    (id: string) => (el: HTMLElement | null) => {
      if (el && id === justAdded && scrolled.current !== id) {
        scrolled.current = id;
        el.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    },
    [justAdded],
  );

  return { justAdded, markAdded, rowRef };
}
