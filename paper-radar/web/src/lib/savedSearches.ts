/** Saved searches and their suggestions (issue #164): types and labels. The
 *  calls are in lib/api.ts. Searches and suggestions are the signed-in
 *  person's own; what they import goes to the lab's library. */

export const SAVED_SEARCHES_FEATURE = "saved_searches";

export type SourceKey = "pubmed" | "biorxiv" | "arxiv";

/** The sources a search can run on, in the order the API uses. */
export const SOURCES: { key: SourceKey; label: string }[] = [
  { key: "pubmed", label: "PubMed" },
  { key: "biorxiv", label: "bioRxiv / medRxiv" },
  { key: "arxiv", label: "arXiv" },
];

/** arXiv subjects new searches keep to: all of quantitative biology,
 *  cross-lists included. Empty means all of arXiv. */
export const ARXIV_BIOLOGY = ["q-bio"];

/** Where a suggested paper came from (bioRxiv and medRxiv apart). */
export const PAPER_SOURCE_LABEL: Record<string, string> = {
  pubmed: "PubMed",
  biorxiv: "bioRxiv",
  medrxiv: "medRxiv",
  arxiv: "arXiv",
};

export interface SavedSearch {
  id: string;
  name: string;
  query: string;
  sources: SourceKey[];
  /** arXiv subject codes it keeps to on arXiv; empty = all of arXiv. */
  arxiv_categories: string[];
  /** The person's order, highest priority first. */
  position: number;
  active: boolean;
  last_run_at: string | null;
  last_error: string | null;
  /** Suggestions from this search still waiting for an answer. */
  pending: number;
}

export interface FoundPaper {
  source: string;
  url: string;
  title: string;
  doi: string | null;
  pmid: string | null;
  authors: string[];
  venue: string | null;
  published_on: string | null;
  abstract: string | null;
  /** Preview only: the lab has it already. */
  in_lab: boolean;
}

export interface Suggestion {
  id: string;
  saved_search_id: string | null;
  /** Every remaining search that found it; empty if they were all deleted. */
  search_ids: string[];
  /** How well it fits the person's taste (cosine similarity, -1..1); null
   *  until the daily job has embedded the paper, for someone Atlas knows
   *  nothing about yet, or when the list was asked for newest first. */
  score: number | null;
  created_at: string;
  paper: FoundPaper;
}

export interface SourceResult {
  source: SourceKey;
  /** How many the past week found (up to the per-source cap). */
  count: number;
  /** The first few. */
  papers: FoundPaper[];
  error: string | null;
}

export interface SearchFields {
  name: string;
  query: string;
  sources: SourceKey[];
  arxiv_categories: string[];
}

/** A ready-made search to start from, built from the person's tags. */
export interface SearchIdea {
  name: string;
  query: string;
  /** Where it came from: "A tag you follow". */
  reason: string;
}

/** "PubMed, arXiv" */
export function sourcesLabel(sources: SourceKey[]): string {
  return SOURCES.filter((s) => sources.includes(s.key))
    .map((s) => s.label)
    .join(", ");
}
