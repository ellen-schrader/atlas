import { type RefObject, useLayoutEffect, useState } from "react";

/** The content-box width of `ref`'s element, kept current with a ResizeObserver.
 *  0 until the first measurement. Layout decisions that depend on how much room
 *  a block actually has (rather than on the viewport) read this instead of a
 *  media query — the nav, for one, takes a different share of the screen at
 *  different widths. */
export function useElementWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}
