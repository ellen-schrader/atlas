import type { Endpoint, Extraction } from "@/lib/extraction";

/** Comparing 2–4 trials from their extractions: which endpoints line up, what
 *  differs between them, and where their enrolment differs. Pure functions, so
 *  the rules are tested (compare.test.ts). Descriptive only: trials aren't
 *  randomised against each other. */

export interface CompareTrial {
  id: string;
  name: string;
  extraction: Extraction;
}

/** Up to four trials: colour (validated, both themes: index.css --cmp-*) and
 *  shape, so a trial is never told apart by colour alone. */
export const MARKERS = ["circle", "square", "diamond", "triangle"] as const;
export type Marker = (typeof MARKERS)[number];
export const MAX_COMPARE = 4;

export function trialColour(i: number): string {
  return `var(--cmp-${(i % MAX_COMPARE) + 1})`;
}

const norm = (s: string | null | undefined) =>
  (s ?? "").toLowerCase().replace(/\s+/g, " ").replace(/[‐–—]/g, "-").trim();

/** A subgroup row ("pCR (PD-L1-positive)") rather than the whole population. */
const isSubgroup = (e: Endpoint) => /\(.+\)/.test(e.name);

const ROLE_ORDER: Endpoint["role"][] = [
  "primary",
  "co_primary",
  "key_secondary",
  "secondary",
  "exploratory",
];

function best(cands: Endpoint[]): Endpoint | null {
  const whole = cands.filter((e) => !isSubgroup(e));
  const pool = whole.length ? whole : cands;
  return (
    [...pool].sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role))[0] ?? null
  );
}

/** The trial's pCR (whole population, most primary role), if reported as a rate. */
export function pcrOf(x: Extraction): Endpoint | null {
  return best(
    x.endpoints.filter(
      (e) => e.kind === "rate" && /\bpcr\b/i.test(e.name) && e.exp_value != null && e.ctrl_value != null,
    ),
  );
}

const HR_PREFERENCE = ["EFS", "IDFS", "DFS", "PFS", "OS"];

/** The trial's hazard ratio for an endpoint ("EFS"), whole population. */
export function hrOf(x: Extraction, name: string): Endpoint | null {
  const target = name.toUpperCase();
  return best(
    x.endpoints.filter(
      (e) =>
        e.kind === "hazard_ratio" &&
        e.hr != null &&
        e.name.replace(/\(.+\)/, "").trim().toUpperCase() === target,
    ),
  );
}

/** The time-to-event endpoint most of the trials report, by preference. */
export function sharedHrEndpoint(trials: CompareTrial[]): string | null {
  let pick: string | null = null;
  let count = 0;
  for (const name of HR_PREFERENCE) {
    const n = trials.filter((t) => hrOf(t.extraction, name)).length;
    if (n > count) {
      pick = name;
      count = n;
    }
  }
  return count >= 1 ? pick : null;
}

/** "pCR +17 pp · EFS HR 0.76": the one-line result for a trial row. */
export function headline(x: Extraction): string {
  const parts: string[] = [];
  const pcr = pcrOf(x);
  if (pcr) {
    const d = pcr.difference ?? (pcr.exp_value! - pcr.ctrl_value!);
    parts.push(`pCR ${d >= 0 ? "+" : ""}${Math.round(d * 10) / 10} pp`);
  }
  for (const name of HR_PREFERENCE) {
    const e = hrOf(x, name);
    if (e) {
      parts.push(`${name === "IDFS" ? "iDFS" : name} HR ${e.hr}`);
      break;
    }
  }
  return parts.join(" · ");
}

// --- what differs ---------------------------------------------------------------

export interface DiffItem {
  key: string;
  /** Value per trial, in trial order; null where not extracted. */
  values: (string | null)[];
  /** "same" only when every trial reports the same value; "differs" when two
   *  reported values disagree; otherwise "unknown" (some trials don't say). */
  status: "same" | "differs" | "unknown";
  /** Trials whose value isn't the most common one (when it differs). */
  outliers: number[];
}

export function contextValue(x: Extraction, key: string): string | null {
  return x.context.find((c) => c.key === key)?.value ?? null;
}

export function diffItems(trials: CompareTrial[], keys: string[]): DiffItem[] {
  return keys.map((key) => {
    const values = trials.map((t) => contextValue(t.extraction, key));
    const known = values.map((v, i) => [norm(v), i] as const).filter(([v]) => v);
    if (!known.length) return { key, values, status: "unknown" as const, outliers: [] };
    const counts = new Map<string, number>();
    for (const [v] of known) counts.set(v, (counts.get(v) ?? 0) + 1);
    const [top, topN] = [...counts].sort((a, b) => b[1] - a[1])[0];
    const differs = counts.size > 1;
    return {
      key,
      values,
      status: differs
        ? ("differs" as const)
        : known.length === trials.length
          ? ("same" as const)
          : ("unknown" as const),
      // Only a clear majority makes the others "outliers": 2 vs 2 has none.
      outliers: differs && topN > known.length / 2 ? known.filter(([v]) => v !== top).map(([, i]) => i) : [],
    };
  });
}

/** Trials whose pCR isn't directly comparable with the rest: its definition
 *  differs from the majority's (e.g. ypT0 ypN0 vs ypT0/is ypN0). */
export function pcrNotComparable(trials: CompareTrial[]): Set<number> {
  return new Set(diffItems(trials, ["pcr_definition"])[0].outliers);
}

// --- enrolment -----------------------------------------------------------------------

export type Cell =
  | { state: "value"; pct: number; flag: "up" | "down" | null; othersMean: number | null }
  | { state: "not_allowed" }
  | { state: "not_reported" };

export interface EnrolmentRow {
  dimension: string;
  category: string;
  cells: Cell[];
  differs: boolean;
}

/** A difference this large, in percentage points, from the other trials' mean
 *  is flagged (the mock-up's rule). */
export const DIFF_PP = 15;

export function enrolmentRows(trials: CompareTrial[], dimensions: Record<string, string[]>): EnrolmentRow[] {
  const rows: EnrolmentRow[] = [];
  for (const [dimension, categories] of Object.entries(dimensions)) {
    for (const category of categories) {
      const raw: Cell[] = trials.map((t) => {
        const d = t.extraction.enrolment.dimensions.find((x) => x.key === dimension);
        const c = d?.categories.find((x) => x.label === category);
        if (!d || !c) return { state: "not_reported" };
        if (c.eligibility === "not_allowed") return { state: "not_allowed" };
        if (c.overall_pct == null) return { state: "not_reported" };
        return { state: "value", pct: c.overall_pct, flag: null, othersMean: null };
      });
      const cells = raw.map((cell, i) => {
        if (cell.state !== "value") return cell;
        // A trial that excluded the category counts as 0% of its patients.
        const others = raw
          .filter((_, j) => j !== i)
          .flatMap((o) => (o.state === "value" ? [o.pct] : o.state === "not_allowed" ? [0] : []));
        if (!others.length) return cell;
        const mean = others.reduce((a, b) => a + b, 0) / others.length;
        const flag =
          Math.abs(cell.pct - mean) >= DIFF_PP ? (cell.pct > mean ? ("up" as const) : ("down" as const)) : null;
        return { ...cell, flag, othersMean: Math.round(mean) };
      });
      rows.push({
        dimension,
        category,
        cells,
        differs: cells.some((c) => c.state === "value" && c.flag !== null),
      });
    }
  }
  return rows;
}

// --- how far the lab has checked it -----------------------------------------------------

/** The groups the trial page can mark verified, for this extraction. */
export function reviewGroups(x: Extraction): string[] {
  return [
    "design",
    ...(x.schedule.length ? ["schedule"] : []),
    ...x.endpoints.map((_, i) => `endpoints.${i}`),
    ...(x.adverse_events.length ? ["adverse_events"] : []),
    "enrolment",
    ...(x.context.length ? ["context"] : []),
  ];
}

export function verification(x: Extraction, reviewed: Set<string>): "Verified" | "Partly verified" | "Not verified" {
  const groups = reviewGroups(x);
  const n = groups.filter((g) => reviewed.has(g)).length;
  return n === 0 ? "Not verified" : n === groups.length ? "Verified" : "Partly verified";
}
