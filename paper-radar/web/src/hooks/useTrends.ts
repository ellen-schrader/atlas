import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

// The trend aggregates don't need to be live (docs/dashboard.md §6).
const STALE = 10 * 60 * 1000;

export interface TrendingTag {
  tag: string;
  /** Papers posted with this tag in the last `days`. */
  n: number;
  /** …and in the `days` before that. */
  prev: number;
}

export interface TrendingAuthor {
  author: string;
  n: number;
  /** Distinct people in the lab who shared their papers. */
  sharers: number;
}

export interface TagWeek {
  tag: string;
  week: string; // ISO date, Monday of the week
  n: number;
}

export function useTrendingTags(teamId: string, days = 30, limit = 6) {
  return useQuery({
    queryKey: ["trending-tags", teamId, days, limit],
    staleTime: STALE,
    queryFn: async (): Promise<TrendingTag[]> => {
      const { data, error } = await supabase.rpc("trending_tags", {
        p_team: teamId,
        p_days: days,
        p_limit: limit,
      });
      if (error) throw error;
      return (data ?? []) as TrendingTag[];
    },
  });
}

export function useTrendingAuthors(teamId: string, days = 30, limit = 5) {
  return useQuery({
    queryKey: ["trending-authors", teamId, days, limit],
    staleTime: STALE,
    queryFn: async (): Promise<TrendingAuthor[]> => {
      const { data, error } = await supabase.rpc("trending_authors", {
        p_team: teamId,
        p_days: days,
        p_limit: limit,
      });
      if (error) throw error;
      return (data ?? []) as TrendingAuthor[];
    },
  });
}

/** Weekly counts for `tags` over the last `weeks`, zero-filled server-side. */
export function useTagVolume(teamId: string, tags: string[], weeks = 12) {
  return useQuery({
    queryKey: ["tag-volume", teamId, weeks, tags],
    enabled: tags.length > 0,
    staleTime: STALE,
    queryFn: async (): Promise<TagWeek[]> => {
      const { data, error } = await supabase.rpc("tag_volume", {
        p_team: teamId,
        p_weeks: weeks,
        p_tags: tags,
      });
      if (error) throw error;
      return (data ?? []) as TagWeek[];
    },
  });
}
