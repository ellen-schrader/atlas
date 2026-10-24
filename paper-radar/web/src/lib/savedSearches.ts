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
}

/** "PubMed, arXiv" */
export function sourcesLabel(sources: SourceKey[]): string {
  return SOURCES.filter((s) => sources.includes(s.key))
    .map((s) => s.label)
    .join(", ");
}
