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
