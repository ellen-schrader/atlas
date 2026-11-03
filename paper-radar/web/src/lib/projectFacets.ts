import type { Closeness, Follow } from "@/lib/projects";

export type FacetKind = "tag" | "lab";
export type Range = "all" | "year" | "month";

export const RANGES: { value: Range; label: string }[] = [
  { value: "all", label: "All time" },
  { value: "year", label: "12 months" },
  { value: "month", label: "30 days" },
];

export const RANGE_SUB: Record<Range, string> = {
  all: "per year published",
  year: "per month added",
  month: "per 5 days added",
};

export interface FacetItem {
  kind: FacetKind;
  key: string;
  /** Related papers with it that are in the project. */
  inCount: number;
  /** Related papers with it: the project's own and the closest others. */
  related: number;
  /** Related ones not in the project: what "N not in it" opens. */
  gap: number;
  /** Related papers over the range, oldest first, for the sparkline. */
  series: number[];
  followed: boolean;
}

const DAY = 86_400_000;

/** Which bucket of the range a paper falls in, or -1 outside it. Publication
 *  year for all time (the last eight years); the date the lab added it for the
 *  12-month and 30-day ranges. */
export function bucketOf(range: Range, info: Pick<Closeness, "year" | "posted_at">, now: Date): number {
  if (range === "all") {
    if (info.year == null) return -1;
    const i = 7 - (now.getFullYear() - info.year);
    return i >= 0 && i <= 7 ? i : -1;
  }
  const age = now.getTime() - new Date(info.posted_at).getTime();
  if (Number.isNaN(age) || age < 0) return -1;
  if (range === "year") {
    const posted = new Date(info.posted_at);
    const months = (now.getFullYear() - posted.getFullYear()) * 12 + now.getMonth() - posted.getMonth();
    return months >= 0 && months <= 11 ? 11 - months : -1;
  }
  const i = 5 - Math.floor(age / (5 * DAY));
  return i >= 0 && i <= 5 ? i : -1;
}

export function bucketCount(range: Range): number {
  return range === "all" ? 8 : range === "year" ? 12 : 6;
}

/** Whether a paper has the tag, or is from the lab. */
export function hasFacet(row: Pick<Closeness, "tags" | "lab"> | undefined, kind: FacetKind, key: string): boolean {
  if (!row) return false;
  return kind === "tag" ? (row.tags ?? []).includes(key) : row.lab === key;
}

/** Tags or labs over the project's related pool, followed first, then the ones
 *  with most related papers left out of the project. */
export function facetItems(
  kind: FacetKind,
  rows: Closeness[],
  follows: Follow[],
  range: Range,
  { limit = 6, now = new Date() }: { limit?: number; now?: Date } = {},
): FacetItem[] {
  const n = bucketCount(range);
  const acc = new Map<string, FacetItem>();
  for (const row of rows) {
    if (!row.related) continue;
    const keys = kind === "tag" ? new Set(row.tags ?? []) : row.lab ? new Set([row.lab]) : new Set<string>();
    const b = bucketOf(range, row, now);
    for (const key of keys) {
      let it = acc.get(key);
      if (!it) {
        it = { kind, key, inCount: 0, related: 0, gap: 0, series: new Array(n).fill(0), followed: false };
        acc.set(key, it);
      }
      it.related++;
      if (row.state === "in") it.inCount++;
      else it.gap++;
      if (b >= 0) it.series[b]++;
    }
  }
  const followed = new Set(follows.filter((f) => f.kind === kind).map((f) => f.value));
  for (const key of followed) {
    if (!acc.has(key))
      acc.set(key, { kind, key, inCount: 0, related: 0, gap: 0, series: new Array(n).fill(0), followed: true });
  }
  const items = [...acc.values()].map((it) => ({ ...it, followed: followed.has(it.key) }));
  // A tag or lab seen once among the related papers says little: keep those
  // out unless followed.
  return items
    .filter((it) => it.followed || it.related >= 2)
    .sort(
      (a, b) =>
        Number(b.followed) - Number(a.followed) ||
        b.gap - a.gap ||
        b.related - a.related ||
        a.key.localeCompare(b.key),
    )
    .slice(0, Math.max(limit, followed.size));
}

/** An SVG path for a 100 × 22 sparkline. */
export function sparkPath(series: number[]): { line: string; area: string } {
  const max = Math.max(1, ...series);
  const n = series.length;
  const pts = series.map((v, i) => [((i / Math.max(1, n - 1)) * 100).toFixed(1), (20 - (v / max) * 18).toFixed(1)]);
  const line = "M" + pts.map((p) => p.join(",")).join("L");
  return { line, area: `${line}L100,22L0,22Z` };
}
