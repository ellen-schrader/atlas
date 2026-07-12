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

/** One paper on the GET /overview UMAP layout. */
export interface OverviewPoint {
  paper_id: string;
  x: number;
  y: number;
  title: string | null;
  venue: string | null;
  year: number | null;
  keywords: string[];
  tags: string[]; // LLM topical tags
  lab: string | null; // last author — proxy for the source lab
  cluster: number;
  reactions: number;
  comments: number;
}

/** A named theme cluster (LLM-labeled from its papers' titles). */
export interface Cluster {
  id: number;
  label: string;
  description: string;
  size: number;
}

export interface OverviewStats {
  over_time: { month: string; count: number }[];
  by_venue: { venue: string; count: number }[];
  by_year: { year: number; count: number }[];
  by_lab: { lab: string; count: number }[];
  by_tag: { tag: string; count: number }[];
}

export interface OverviewData {
  points: OverviewPoint[];
  clusters: Cluster[];
  stats: OverviewStats;
  total: number; // posts in the lab
  embedded: number; // posts with an embedded paper (points returned)
}
