import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getProject,
  listProjects,
  paperInfo,
  projectCloseness,
  projectFollows,
  projectPapers,
  projectSummaries,
} from "@/lib/projects";

/** Every project the user can see in the lab, most recently changed first. */
export function useProjectList(teamId: string, enabled = true) {
  return useQuery({
    queryKey: ["projects", teamId],
    queryFn: () => listProjects(teamId),
    enabled,
  });
}

/** In / suggested / new counts per project, for the index. */
export function useProjectSummaries(teamId: string, enabled = true) {
  return useQuery({
    queryKey: ["project-summaries", teamId],
    queryFn: () => projectSummaries(teamId),
    enabled,
  });
}

export function useProject(id: string | undefined) {
  return useQuery({
    queryKey: ["project", id],
    queryFn: () => getProject(id as string),
    enabled: !!id,
  });
}

/** Every library paper's closeness to the project (public.project_closeness). */
export function useCloseness(id: string | undefined) {
  return useQuery({
    queryKey: ["project-closeness", id],
    queryFn: () => projectCloseness(id as string),
    enabled: !!id,
    staleTime: 60_000,
  });
}

export function useProjectPapers(id: string | undefined) {
  return useQuery({
    queryKey: ["project-papers", id],
    queryFn: () => projectPapers(id as string),
    enabled: !!id,
  });
}

export function useProjectFollows(id: string | undefined) {
  return useQuery({
    queryKey: ["project-follows", id],
    queryFn: () => projectFollows(id as string),
    enabled: !!id,
  });
}

/** Titles, tags and labs for a set of papers. Keyed by the sorted ids, so the
 *  same set from another view is a cache hit. */
export function usePaperInfo(teamId: string, ids: string[]) {
  const key = [...ids].sort();
  return useQuery({
    queryKey: ["project-paper-info", teamId, key],
    queryFn: () => paperInfo(teamId, key),
    enabled: key.length > 0,
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  });
}

/** After any change to a project's papers, follows or settings. */
export function useRefreshProject() {
  const qc = useQueryClient();
  return (id: string, teamId: string) =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["project", id] }),
      qc.invalidateQueries({ queryKey: ["project-closeness", id] }),
      qc.invalidateQueries({ queryKey: ["project-papers", id] }),
      qc.invalidateQueries({ queryKey: ["project-follows", id] }),
      qc.invalidateQueries({ queryKey: ["projects", teamId] }),
      qc.invalidateQueries({ queryKey: ["project-summaries", teamId] }),
    ]);
}
