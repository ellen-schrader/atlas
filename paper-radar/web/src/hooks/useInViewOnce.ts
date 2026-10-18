import { type RefObject, useLayoutEffect, useState } from "react";

export type RevealState = "static" | "armed" | "played";

/** Plays a reveal once, the first time `ref`'s element scrolls into view.
 *
 *  Starts "static": the final, fully visible state, which is what a screenshot,
 *  a crawler or a visitor without IntersectionObserver gets. After mount it is
 *  "armed" (CSS hides the parts that animate in), then "played" once in view.
 *  Under prefers-reduced-motion it stays "static", so nothing is ever hidden
 *  without the animation that brings it back. */
export function useInViewOnce(
  ref: RefObject<HTMLElement | null>,
  threshold = 0.35,
): RevealState {
  const [state, setState] = useState<RevealState>("static");
  // Layout effect: arming before the first paint, so a section already on screen
  // at load isn't drawn visible, hidden, then animated back in.
  useLayoutEffect(() => {
    const el = ref.current;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!el || reduce || !("IntersectionObserver" in window)) return;
    setState("armed");
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        setState("played");
        io.disconnect();
      },
      { threshold },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref, threshold]);
  return state;
}
