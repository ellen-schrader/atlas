export interface Profile {
  id: string;
  display_name: string;
  interests: string[];
  profile_md: string;
  created_at: string;
}

export interface Team {
  id: string;
  name: string;
  slug: string;
  /** High-entropy, revocable invite code — share this to let people join. */
  join_code: string;
  created_by: string | null;
  created_at: string;
}

export interface Membership {
  role: "owner" | "member";
  teams: Team;
}

export interface Paper {
  id: string;
  url: string;
  doi: string | null;
  title: string | null;
  authors: string[];
  abstract: string | null;
  venue: string | null;
  year: number | null;
  keywords: string[];
  tags: string[];
  code_url: string | null;
  data_url: string | null;
  enriched_at: string | null;
  /** Last hand correction or re-resolve. Also the concurrency token an edit
   *  must send back. Who made it lives where members cannot read it, since it
   *  would identify someone in another lab; paper_editor() answers for the card. */
  edited_at: string | null;
  /** Fields a person corrected by hand; the resolver never overwrites these. */
  edited_fields: string[];
}

/** The `papers` columns a Paper holds, for embeds like `papers(${PAPER_COLUMNS})`.
 *  Never `papers(*)`: it would drag the 1024-dim embedding into every load. */
export const PAPER_COLUMNS =
  "id, url, doi, title, authors, abstract, venue, year, keywords, tags, code_url, data_url, enriched_at, edited_at, edited_fields";

export interface PaperPost {
  id: string;
  posted_at: string;
  note: string | null;
  posted_by: string | null;
  posted_by_label: string | null;
  poster?: { display_name: string } | null; // joined profile — fallback when label is null
  source: string; // 'web' | 'teams_pdf' | 'teams' — how the paper reached the lab
  tags: string[]; // lab-scoped custom tags (distinct from papers.tags/keywords)
  papers: Paper; // the joined canonical paper
}

/** One result from POST /search/semantic. */
export interface SemanticHit {
  similarity: number;
  post: PaperPost;
}

/** One personalized paper from GET /recommendations (taste-vector ranked). */
export interface Recommendation {
  similarity: number;
  post: PaperPost;
  /** Why this paper was picked; absent for the cold-start recency fallback. */
  reason?: RecommendationReason | null;
}

/** The signal behind a recommendation (docs/dashboard.md §3.4; the rules are in
 *  api/app.py above _REASON_MIN_SIMILARITY). `ref_label` is the paper title for
 *  similar_*, the first profile tag for "profile" ("" = none matched), and who
 *  shared it for "new". */
export interface RecommendationReason {
  kind:
    | "similar_saved"
    | "similar_posted"
    | "similar_read"
    | "similar_reacted"
    | "similar_liked"
    | "similar_discussed"
    | "similar_reading"
    | "profile"
    | "engagement"
    | "new"
    | "tag"
    | "author";
  ref_id: string | null;
  ref_label: string;
  extra_labels?: string[];
}

/** One row from the `similar_papers` RPC ("find similar" in the paper modal). */
export interface SimilarPaper {
  post_id: string;
  paper_id: string;
  title: string | null;
  venue: string | null;
  year: number | null;
  similarity: number;
}
