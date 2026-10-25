import { useEffect } from "react";

/** The landing page's tab title, and what a page falls back to when it has none. */
export const DEFAULT_TITLE = "Atlas · Paper library for labs";

const MAX_LEN = 50;

/** Sets the browser tab to "{title} · Atlas", page first so it survives a
 *  narrow tab. Pass null while the page's name is still loading; the tab keeps
 *  the bare "Atlas" until it arrives. Long names (paper titles) are cut at 50
 *  characters. */
export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    if (!title) {
      document.title = "Atlas";
      return;
    }
    const t = title.length > MAX_LEN ? `${title.slice(0, MAX_LEN - 1).trimEnd()}…` : title;
    document.title = `${t} · Atlas`;
  }, [title]);
}
