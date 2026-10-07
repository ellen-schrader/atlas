/** Home's responsive frame, keyed off the width of the app shell (nav included),
 *  per docs/dashboard.md §2.2. Every block on the page sits on the same N-column
 *  track set, so card edges line up from row to row; wider screens get *more*
 *  columns (more recommendation cards), never wider ones. */
export type HomeTier = "mobile" | "tablet" | "laptop" | "desktop";

export interface HomeFrame {
  tier: HomeTier;
  /** Columns in the shared grid. 1 below the laptop tier. */
  cols: number;
  /** Recommendation cards per visible page (tablet shows 2 in a 1-column grid). */
  recsPerPage: number;
  padding: string;
  /** Vertical gap between blocks, px. */
  blockGap: number;
}

export const COL_GAP = 24;
/** Width of the full sidebar in Layout. */
const SIDEBAR = 232;

export function homeFrame(shellWidth: number): HomeFrame {
  if (shellWidth < 640) {
    return { tier: "mobile", cols: 1, recsPerPage: 1, padding: "20px 16px 32px", blockGap: 26 };
  }
  if (shellWidth < 900) {
    return { tier: "tablet", cols: 1, recsPerPage: 2, padding: "28px", blockGap: 30 };
  }
  if (shellWidth < 1360) {
    return { tier: "laptop", cols: 3, recsPerPage: 3, padding: "30px 32px 40px", blockGap: 30 };
  }
  const content = shellWidth - SIDEBAR - 80;
  const cols = content >= 1660 ? 5 : content >= 1400 ? 4 : 3;
  return { tier: "desktop", cols, recsPerPage: cols, padding: "34px 40px 44px", blockGap: 30 };
}

/** `grid-template-columns` for the shared track set. */
export function gridColumns(cols: number): string {
  return `repeat(${cols}, minmax(0, 1fr))`;
}

/** Width of one card that spans exactly one grid column. */
export function cardWidth(perPage: number): string {
  return `calc((100% - ${(perPage - 1) * COL_GAP}px) / ${perPage})`;
}
