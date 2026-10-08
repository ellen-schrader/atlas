import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useProfile } from "@/hooks/useProfile";
import { supabase } from "@/lib/supabase";
import type { Profile } from "@/lib/types";

/** The tags the user follows (profiles.interests): they lift papers in Discover
 *  and give "Tagged X, which you follow" reasons. Per person, across labs.
 *
 *  Writes are optimistic — the profile cache flips at once and rolls back if the
 *  update fails — and refresh recommendations, which rank with them. */
export function useFollowedTags(userId: string) {
  const qc = useQueryClient();
  const { data: profile } = useProfile(userId);
  const follows: string[] = profile?.interests ?? [];

  const save = useCallback(
    async (next: string[]): Promise<boolean> => {
      const key = ["profile", userId];
      const before = qc.getQueryData<Profile | null>(key);
      qc.setQueryData<Profile | null>(key, (p) => (p ? { ...p, interests: next } : p));
      const { error } = await supabase.from("profiles").update({ interests: next }).eq("id", userId);
      if (error) {
        qc.setQueryData(key, before);
        return false;
      }
      void qc.invalidateQueries({ queryKey: ["recommendations"] });
      return true;
    },
    [qc, userId],
  );

  const toggle = useCallback(
    (tag: string) =>
      save(follows.includes(tag) ? follows.filter((t) => t !== tag) : [...follows, tag]),
    [follows, save],
  );

  return { follows, isFollowing: (tag: string) => follows.includes(tag), toggle, save };
}
