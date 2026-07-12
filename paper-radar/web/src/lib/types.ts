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
}

export interface PaperPost {
  id: string;
  posted_at: string;
  note: string | null;
  posted_by: string | null;
  posted_by_label: string | null;
  poster?: { display_name: string } | null; // joined profile — fallback when label is null
  tags: string[]; // lab-scoped custom tags (distinct from papers.tags/keywords)
  papers: Paper; // the joined canonical paper
}

/** One result from POST /search/semantic. */
export interface SemanticHit {
  similarity: number;
  post: PaperPost;
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

/** One paper on the GET /map UMAP layout. */
export interface MapPoint {
  paper_id: string;
  x: number;
  y: number;
  title: string | null;
  venue: string | null;
  year: number | null;
  tags: string[];
}

export interface MapData {
  points: MapPoint[];
  total: number; // posts in the lab
  embedded: number; // posts with an embedded paper (points returned)
}
