/** Preprints are told apart by their venue: the resolver names the server
 *  ("bioRxiv", "arXiv", …) on every preprint it adds, and migration
 *  20261017130000_preprint_venues named it on the ones already stored. Mirrors
 *  `_PREPRINT_VENUE_RE` in paper_radar/ingest/metadata.py. */
const PREPRINT_VENUE =
  /\b(?:bio|med)rxiv\b|\barxiv\b|research square|\bssrn\b|preprints\.org|osf preprints|authorea/i;

export function isPreprintVenue(venue: string | null | undefined): boolean {
  return Boolean(venue && PREPRINT_VENUE.test(venue));
}

/** A published paper's earlier preprint version (a `paper_aliases` row). */
export interface PreprintLink {
  url: string | null;
  doi: string | null;
  venue: string | null;
}

/** Where a preprint link should go: its own URL, else its DOI. */
export function preprintHref(p: PreprintLink): string | null {
  return p.url ?? (p.doi ? `https://doi.org/${p.doi}` : null);
}
