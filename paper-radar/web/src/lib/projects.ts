import { supabase } from "@/lib/supabase";

/** Projects (docs/PROJECTS_PLAN.md). Dark unless the `projects` feature is on
 *  for the lab or the person. */
export const PROJECTS_FEATURE = "projects";

export type Visibility = "private" | "lab" | "people";
export type SuggestLevel = "fewer" | "balanced" | "more";

export interface Project {
  id: string;
  team_id: string;
  /** Null once the owner has deleted their account. */
  owner_id: string | null;
  name: string;
  description: string;
  visibility: Visibility;
  suggest_level: SuggestLevel;
  created_at: string;
  updated_at: string;
  project_people: { user_id: string }[];
}

export const PROJECT_COLUMNS =
  "id, team_id, owner_id, name, description, visibility, suggest_level, created_at, updated_at, project_people(user_id)";

export const VISIBILITY: Record<Visibility, { label: string; sub: string }> = {
  private: { label: "Only you", sub: "Nobody else sees it" },
  lab: { label: "Whole lab", sub: "Everyone in the lab can see it and add papers" },
  people: { label: "Chosen people", sub: "Only the lab members you pick" },
};

export const LEVELS: { value: SuggestLevel; label: string }[] = [
  { value: "fewer", label: "Fewer" },
  { value: "balanced", label: "Balanced" },
  { value: "more", label: "More" },
];

/** One paper of the lab, as public.project_closeness returns it. */
export interface Closeness {
  paper_id: string;
  post_id: string;
  year: number | null;
  posted_at: string;
  /** To the closest paper in the project (for one in it: the closest other
   *  one), or to the description while the project has fewer than three. */
  similarity: number | null;
  nearest_id: string | null;
  state: "in" | "dismissed" | null;
  /** In the related pool that "Around this project" counts over. */
  related: boolean;
  suggested: "close" | "tag" | "lab" | null;
  /** The followed tag or lab behind a 'tag' / 'lab' suggestion. */
  via: string | null;
  cutoff: number;
  /** The lab's tags for it, else the paper's own. */
  tags: string[];
  /** Its last author who is a person: the paper's "lab" (public.last_person_author). */
  lab: string | null;
}

export interface ProjectPaper {
  paper_id: string;
  state: "in" | "dismissed";
  added_by: string | null;
  added_at: string;
}

export interface Follow {
  kind: "tag" | "lab";
  value: string;
}

/** What the lists, cards and facets need about a paper. */
export interface PaperInfo {
  id: string;
  title: string | null;
  authors: string[];
  venue: string | null;
  year: number | null;
  doi: string | null;
  url: string | null;
  abstract: string | null;
  /** The lab's tags for it, else the paper's own (post_tags in SQL). */
  tags: string[];
  posted_at: string;
}

export function canEdit(project: Project, userId: string): boolean {
  return project.owner_id === userId;
}

/** Who is on a project's people list, which only counts while it is shared
 *  with chosen people (the list is kept when visibility changes). */
export function sharedWith(project: Project): string[] {
  return project.visibility === "people" ? project.project_people.map((p) => p.user_id) : [];
}

/** The owner, then the people it is shared with: the avatars it shows. */
export function projectPeople(project: Project): string[] {
  return [project.owner_id, ...sharedWith(project)].filter((u): u is string => !!u);
}

// --- reads ------------------------------------------------------------------

export async function listProjects(teamId: string): Promise<Project[]> {
  const { data, error } = await supabase
    .from("projects")
    .select(PROJECT_COLUMNS)
    .eq("team_id", teamId)
    .order("updated_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as unknown as Project[];
}

export async function getProject(id: string): Promise<Project | null> {
  const { data, error } = await supabase.from("projects").select(PROJECT_COLUMNS).eq("id", id);
  if (error) throw error;
  return ((data ?? [])[0] as unknown as Project) ?? null;
}

/** Which of the lab's projects (that the user can see) each paper is in. */
export async function projectsByPaper(teamId: string): Promise<Map<string, string[]>> {
  const { data, error } = await supabase
    .from("project_papers")
    .select("project_id, paper_id, projects!inner(team_id)")
    .eq("state", "in")
    .eq("projects.team_id", teamId);
  if (error) throw error;
  const out = new Map<string, string[]>();
  for (const r of (data ?? []) as { project_id: string; paper_id: string }[]) {
    out.set(r.paper_id, [...(out.get(r.paper_id) ?? []), r.project_id]);
  }
  return out;
}

/** How many papers are in each of these projects, in one request. */
export async function projectPaperCounts(ids: string[]): Promise<Map<string, number>> {
  const counts = new Map<string, number>(ids.map((id) => [id, 0]));
  if (ids.length === 0) return counts;
  const { data, error } = await supabase
    .from("project_papers")
    .select("project_id")
    .eq("state", "in")
    .in("project_id", ids);
  if (error) throw error;
  for (const r of data ?? []) counts.set(r.project_id, (counts.get(r.project_id) ?? 0) + 1);
  return counts;
}

export async function projectCloseness(id: string): Promise<Closeness[]> {
  const { data, error } = await supabase.rpc("project_closeness", { p_project: id });
  if (error) throw error;
  return (data ?? []) as Closeness[];
}

export async function projectPapers(id: string): Promise<ProjectPaper[]> {
  const { data, error } = await supabase
    .from("project_papers")
    .select("paper_id, state, added_by, added_at")
    .eq("project_id", id);
  if (error) throw error;
  return (data ?? []) as ProjectPaper[];
}

export async function projectFollows(id: string): Promise<Follow[]> {
  const { data, error } = await supabase
    .from("project_follows")
    .select("kind, value")
    .eq("project_id", id)
    .order("created_at");
  if (error) throw error;
  return (data ?? []) as Follow[];
}

/** Ids per request: an `in` filter rides in the URL, so keep it well short of
 *  any proxy's limit. */
const CHUNK = 120;

/** The lab's view of these papers: its tags (else the paper's), its post date. */
export async function paperInfo(teamId: string, ids: string[]): Promise<PaperInfo[]> {
  const out: PaperInfo[] = [];
  for (let i = 0; i < ids.length; i += CHUNK) {
    const { data, error } = await supabase
      .from("paper_posts")
      .select("posted_at, tags, papers(id, title, authors, venue, year, doi, url, abstract, tags)")
      .eq("team_id", teamId)
      .in("paper_id", ids.slice(i, i + CHUNK));
    if (error) throw error;
    for (const row of (data ?? []) as unknown as {
      posted_at: string;
      tags: string[];
      papers: Omit<PaperInfo, "posted_at">;
    }[]) {
      if (!row.papers) continue;
      const p = row.papers;
      out.push({
        ...p,
        authors: p.authors ?? [],
        tags: row.tags?.length ? row.tags : (p.tags ?? []),
        posted_at: row.posted_at,
      });
    }
  }
  return out;
}

// --- writes -----------------------------------------------------------------

export async function deleteProject(id: string): Promise<void> {
  const { error } = await supabase.from("projects").delete().eq("id", id);
  if (error) throw error;
}

/** Put papers in the project, or dismiss them from its suggestions. A paper
 *  that was the other state moves. */
export async function setPapers(
  projectId: string,
  userId: string,
  paperIds: string[],
  state: "in" | "dismissed",
): Promise<void> {
  if (paperIds.length === 0) return;
  const now = new Date().toISOString();
  const { error } = await supabase.from("project_papers").upsert(
    paperIds.map((paper_id) => ({
      project_id: projectId,
      paper_id,
      state,
      added_by: userId,
      added_at: now,
    })),
  );
  if (error) throw error;
}

/** Take papers out of the project, or bring dismissed ones back to suggestions. */
export async function clearPapers(projectId: string, paperIds: string[]): Promise<void> {
  if (paperIds.length === 0) return;
  const { error } = await supabase
    .from("project_papers")
    .delete()
    .eq("project_id", projectId)
    .in("paper_id", paperIds);
  if (error) throw error;
}

export async function setFollow(projectId: string, f: Follow, on: boolean): Promise<void> {
  const { error } = on
    ? await supabase
        .from("project_follows")
        .upsert({ project_id: projectId, ...f }, { ignoreDuplicates: true })
    : await supabase
        .from("project_follows")
        .delete()
        .eq("project_id", projectId)
        .eq("kind", f.kind)
        .eq("value", f.value);
  if (error) throw error;
}

export async function setPerson(projectId: string, userId: string, on: boolean): Promise<void> {
  const { error } = on
    ? await supabase
        .from("project_people")
        .upsert({ project_id: projectId, user_id: userId }, { ignoreDuplicates: true })
    : await supabase
        .from("project_people")
        .delete()
        .eq("project_id", projectId)
        .eq("user_id", userId);
  if (error) throw error;
}

export async function markViewed(projectId: string): Promise<void> {
  await supabase.rpc("mark_project_viewed", { p: projectId });
}
