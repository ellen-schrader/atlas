import { useCallback, useMemo, useState } from "react";

/** Multi-select state for a list: a "selecting" mode plus the chosen ids. Shared by
 *  the Papers and Reading List views so their export flows behave identically. */
export function useSelection() {
  const [selecting, setSelecting] = useState(false);
  const [ids, setIds] = useState<Set<string>>(new Set());

  const toggle = useCallback((id: string) => {
    setIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback((allIds: string[]) => setIds(new Set(allIds)), []);
  const clear = useCallback(() => setIds(new Set()), []);

  const start = useCallback(() => setSelecting(true), []);
  const stop = useCallback(() => {
    setSelecting(false);
    setIds(new Set());
  }, []);

  const isSelected = useCallback((id: string) => ids.has(id), [ids]);

  return useMemo(
    () => ({ selecting, ids, count: ids.size, toggle, selectAll, clear, start, stop, isSelected }),
    [selecting, ids, toggle, selectAll, clear, start, stop, isSelected],
  );
}

export type Selection = ReturnType<typeof useSelection>;
