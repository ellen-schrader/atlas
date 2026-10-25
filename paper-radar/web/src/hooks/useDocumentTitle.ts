import { useEffect } from "react";

/** The landing page's tab title. index.html carries the same string, for the
 *  first paint and for crawlers that don't run the app. */
export const DEFAULT_TITLE = "Atlas · Paper library for labs";

const MAX_LEN = 50;

/** Sets the browser tab to "{title} · Atlas", page first so it survives a
 *  narrow tab. Pass null while the page's name is still loading; the tab shows
 *  the bare "Atlas" until it arrives, and again once the page unmounts, so a
 *  page without a title never inherits the last one. Long names (paper titles)
 *  are cut at 50 characters. `raw` sets the title as given. */
export function useDocumentTitle(title: string | null | undefined, { raw = false } = {}) {
  useEffect(() => {
    if (!title) document.title = "Atlas";
    else if (raw) document.title = title;
    else {
      // By code point, so a cut never splits a surrogate pair.
      const chars = Array.from(title);
      const t = chars.length > MAX_LEN ? `${chars.slice(0, MAX_LEN - 1).join("").trimEnd()}…` : title;
      document.title = `${t} · Atlas`;
    }
    return () => {
      document.title = "Atlas";
    };
  }, [title, raw]);
}
