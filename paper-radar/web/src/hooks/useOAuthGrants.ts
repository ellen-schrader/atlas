import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { OAuthGrant } from "@supabase/supabase-js";

import { supabase } from "@/lib/supabase";

/** The apps this user has let sign in to Atlas on their behalf — in practice,
 *  Claude connections (one per Claude client they connected). */
export function useOAuthGrants() {
  return useQuery({
    queryKey: ["oauth-grants"],
    queryFn: async (): Promise<OAuthGrant[]> => {
      const { data, error } = await supabase.auth.oauth.listGrants();
      if (error) throw error;
      return data ?? [];
    },
  });
}

/** Revoke one app's access. Its sessions end at once, and the database's connector
 *  gate refuses its existing tokens from the next request — not when they expire. */
export function useRevokeGrant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (clientId: string) => {
      const { error } = await supabase.auth.oauth.revokeGrant({ clientId });
      if (error) throw error;
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["oauth-grants"] }),
  });
}
