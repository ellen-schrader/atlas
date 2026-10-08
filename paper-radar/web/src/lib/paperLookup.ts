import type { QueryClient } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

/* Turning what people paste into something the resolver can fetch, and checking
   whether the lab already has it. Shared by AddPaperDialog and Home's omnibar. */

/** Where autofilled metadata came from, in words a researcher recognises. */
export const SOURCE_LABEL: Record<string, string> = {
  arxiv: "arXiv",
  crossref: "Crossref",
  pubmed: "PubMed",
  europepmc: "Europe PMC",
  citation_meta: "the publisher’s page",
};

/** Accept a bare DOI, a `doi:` prefix, or a full doi.org URL — people paste all three.
 *  Returns the bare DOI, which is what `papers.doi` dedupes on: storing the doi.org
 *  URL there instead would never match the same paper added by anyone else. */
export function bareDoi(input: string): string | null {
  const doi = input
    .trim()
    .replace(/^doi:\s*/i, "")
    .replace(/^https?:\/\/(dx\.)?doi\.org\//i, "");
  return /^10\.\d{4,9}\/\S+$/.test(doi) ? doi : null;
}

export function doiUrl(input: string): string | null {
  const doi = bareDoi(input);
  return doi ? `https://doi.org/${doi}` : null;
}

/** A PubMed article link, or an explicit `pmid:12345`, normalised to the canonical
 *  page — the resolver reads the PMID out of exactly this URL shape. A bare number
 *  is deliberately NOT accepted: "2023" is a valid PMID, so treating stray digits as
 *  one would silently resolve an unrelated paper instead of erroring. */
export function pubmedUrl(input: string): string | null {
  const trimmed = input.trim();
  const m =
    trimmed.match(/pubmed\.ncbi\.nlm\.nih\.gov\/([0-9]+)/i) ??
    trimmed.match(/^pmid:\s*([0-9]+)$/i);
  return m ? `https://pubmed.ncbi.nlm.nih.gov/${m[1]}/` : null;
}

/** What people paste is often not a fetchable URL: a bare DOI, a `doi:` handle,
 *  or a scheme-less `arxiv.org/abs/…` (our own placeholder suggests one). The
 *  server only fetches http(s), so build that here rather than bouncing the
 *  paste back with "Only http(s) links can be fetched." */
export function fetchableUrl(input: string): string {
  const viaDoi = doiUrl(input);
  if (viaDoi) return viaDoi;
  const trimmed = input.trim();
  const viaPubmed = pubmedUrl(trimmed);
  if (viaPubmed) return viaPubmed;
  // "arXiv:2401.12345" — the form papers cite themselves by.
  const arxiv = trimmed.match(/^arxiv:\s*(\S+)$/i);
  if (arxiv) return `https://arxiv.org/abs/${arxiv[1]}`;
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) || !trimmed
    ? trimmed
    : `https://${trimmed}`;
}

/** Does the input look like something to ADD rather than to search for: a DOI
 *  (bare, `doi:` or doi.org), a link, an arXiv or PubMed id. Tighter than the
 *  spec's `^(10\.\d|https?:|doi:|arxiv)`, which sent searches like "arxiv
 *  preprints on CRISPR" or a half-typed "https" to Add mode, and missed the
 *  `pmid:` and scheme-less links AddPaperDialog accepts. */
export function looksAddable(input: string): boolean {
  const s = input.trim();
  if (/\s/.test(s)) return false; // nothing addable contains a space
  return /^(10\.\d{4,9}\/|https?:\/\/\S|doi:|arxiv:|pmid:|www\.|arxiv\.org\/|(dx\.)?doi\.org\/|pubmed\.ncbi)/i.test(s);
}

/** Refresh everything that reads a lab's posts after one is added. One list for
 *  both ways in (AddPaperDialog and Home's omnibar), so a new view can't be
 *  remembered in one and forgotten in the other. */
export function invalidateAfterPost(qc: QueryClient, teamId: string): Promise<unknown> {
  return Promise.all(
    [
      "paper-search",
      "paper-count",
      "team-tags",
      "team-venues",
      "paper-lookup",
      "trending-tags",
      "trending-authors",
      "tag-volume",
    ].map((key) => qc.invalidateQueries({ queryKey: [key, teamId] })),
  );
}

export interface Duplicate {
  paperId: string;
  title: string | null;
  /** Who shared it in this lab, and when — for "Already shared by … · 3d ago". */
  sharedBy: string | null;
  sharedAt: string | null;
}

/** Is this paper already posted in the lab? Matches the normalised URL, then the
 *  DOI (a paper added from its publisher page has a different URL from the same
 *  paper pasted as a DOI). Reads through RLS — `papers` is only visible via a post
 *  in one of your labs, which is exactly the question asked. */
export async function findInLab(
  teamId: string,
  resolved: { url_norm: string; doi?: string | null },
): Promise<Duplicate | null> {
  const select =
    "paper_id, posted_at, posted_by_label, poster:profiles!paper_posts_posted_by_fkey(display_name), papers!inner(title)";
  const byUrl = await supabase
    .from("paper_posts")
    .select(select)
    .eq("team_id", teamId)
    .eq("papers.url_norm", resolved.url_norm)
    .maybeSingle();
  let row = byUrl.error ? null : byUrl.data;
  // DOIs are stored case-folded (20260713000000_doi_casefold.sql).
  const doi = resolved.doi ? bareDoi(resolved.doi)?.toLowerCase() : null;
  if (!row && doi) {
    const byDoi = await supabase
      .from("paper_posts")
      .select(select)
      .eq("team_id", teamId)
      .eq("papers.doi", doi)
      .maybeSingle();
    row = byDoi.error ? null : byDoi.data;
  }
  if (!row) return null;
  const r = row as unknown as {
    paper_id: string;
    posted_at: string;
    posted_by_label: string | null;
    poster: { display_name: string } | null;
    papers: { title: string | null } | null;
  };
  return {
    paperId: r.paper_id,
    title: r.papers?.title ?? null,
    sharedBy: r.posted_by_label ?? r.poster?.display_name ?? null,
    sharedAt: r.posted_at,
  };
}
