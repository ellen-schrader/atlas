import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";

export interface McpToolCall {
  id: number;
  tool: string;
  ok: boolean;
  called_at: string;
  user_id: string | null;
}

/** Whether this lab has Claude access switched on. Visible to every member. */
export function useMcpAccess(teamId: string) {
  return useQuery({
    queryKey: ["mcp-access", teamId],
    queryFn: async (): Promise<boolean> => {
      const { data, error } = await supabase
        .from("mcp_access")
        .select("enabled")
        .eq("team_id", teamId)
        .maybeSingle();
      if (error) throw error;
      // No row means nobody has ever turned it on — which is "off", not an error.
      return data?.enabled ?? false;
    },
  });
}

/** Owner-only. The RPC raises 42501 for everyone else, so the error is real, not silent. */
export function useSetMcpAccess(teamId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (enabled: boolean) => {
      const { error } = await supabase.rpc("set_mcp_access", {
        p_team: teamId,
        p_enabled: enabled,
      });
      if (error) throw error;
      return enabled;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["mcp-access", teamId] });
      void qc.invalidateQueries({ queryKey: ["mcp-tool-calls", teamId] });
    },
  });
}

/** What Claude has actually been doing — readable by the whole lab, not just whoever connected. */
export function useMcpToolCalls(teamId: string, limit = 12) {
  return useQuery({
    queryKey: ["mcp-tool-calls", teamId, limit],
    queryFn: async (): Promise<McpToolCall[]> => {
      const { data, error } = await supabase
        .from("mcp_tool_calls")
        .select("id, tool, ok, called_at, user_id")
        .eq("team_id", teamId)
        .order("called_at", { ascending: false })
        .limit(limit);
      if (error) throw error;
      return data ?? [];
    },
    refetchInterval: 15_000, // it's a live log; a stale one invites false confidence
  });
}
