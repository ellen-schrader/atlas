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

/** A mood-board figure: an inspirational publication image, lab-scoped, optionally
 *  linked to a paper. The image itself lives in the private `figures` storage
 *  bucket at `storage_path`; the app resolves short-lived signed URLs to show it. */
export interface Figure {
  id: string;
  team_id: string;
  uploaded_by: string | null;
  storage_path: string;
  title: string;
  caption: string;
  category: string;
  paper_id: string | null;
  tags: string[];
  width: number;
  height: number;
  mime_type: string;
  file_size: number | null;
  created_at: string;
  uploader?: { display_name: string } | null; // joined profile of the uploader
  papers?: { id: string; title: string | null } | null; // joined linked paper (if any)
}
