import type { LoadOptions } from "@/components/SearchableSelect";
import { supabase } from "@/lib/supabase";

/** Loaders for the Papers filter menus: one page of a lab's tags, authors or
 *  venues containing `q`, most papers first (team_tags / team_authors /
 *  team_venues with p_q and p_limit — see 20261010120000_author_filter.sql). */

export function loadTeamTags(teamId: string): LoadOptions {
  return async (q, limit) => {
    const { data, error } = await supabase.rpc("team_tags", { p_team: teamId, p_q: q, p_limit: limit });
    if (error) throw error;
    return ((data ?? []) as { tag: string; n: number }[]).map((r) => ({ value: r.tag, n: r.n }));
  };
}

export function loadTeamAuthors(teamId: string): LoadOptions {
  return async (q, limit) => {
    const { data, error } = await supabase.rpc("team_authors", { p_team: teamId, p_q: q, p_limit: limit });
    if (error) throw error;
    return ((data ?? []) as { author: string; n: number }[]).map((r) => ({ value: r.author, n: r.n }));
  };
}

export function loadTeamVenues(teamId: string): LoadOptions {
  return async (q, limit) => {
    const { data, error } = await supabase.rpc("team_venues", { p_team: teamId, p_q: q, p_limit: limit });
    if (error) throw error;
    return ((data ?? []) as { venue: string; count: number }[]).map((r) => ({ value: r.venue, n: r.count }));
  };
}
