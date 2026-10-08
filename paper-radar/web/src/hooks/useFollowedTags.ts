import { useCallback, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useProfile } from "@/hooks/useProfile";
import { supabase } from "@/lib/supabase";
import type { Profile } from "@/lib/types";

/** The tags the user follows (profiles.interests), set in Settings: they get
 *  their own Discover search and "Tagged X, which you follow" reasons. Per
 *  person, across labs.
 *
 *  Every write replaces the whole array, so two rules keep it from losing tags:
 *  - nothing is written until the profile has loaded (`ready`) — otherwise the
 *    "current" list is [] and following one tag would erase all the others;
 *  - writes run one at a time, each computed from the latest list when it runs,
 *    so quick successive clicks can't land out of order. A failed write
 *    refetches the profile rather than restoring a snapshot that a later,
 *    successful write may have superseded. */
export function useFollowedTags(userId: string) {
  const qc = useQueryClient();
  const { data: profile, isSuccess } = useProfile(userId);
  const ready = isSuccess && profile != null;
  const follows = useMemo(() => profile?.interests ?? [], [profile?.interests]);
  const followed = useMemo(() => new Set(follows), [follows]);
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  const update = useCallback(
    (change: (current: string[]) => string[]): Promise<boolean> => {
      if (!ready) return Promise.resolve(false);
      const key = ["profile", userId];
      const run = queue.current.then(async () => {
        const current = qc.getQueryData<Profile | null>(key)?.interests ?? [];
        const next = change(current);
        qc.setQueryData<Profile | null>(key, (p) => (p ? { ...p, interests: next } : p));
        const { error } = await supabase.from("profiles").update({ interests: next }).eq("id", userId);
        if (error) {
          void qc.invalidateQueries({ queryKey: key });
          return false;
        }
        void qc.invalidateQueries({ queryKey: ["recommendations"] });
        return true;
      });
      queue.current = run.catch(() => undefined);
      return run;
    },
    [qc, ready, userId],
  );

  const follow = useCallback(
    (tag: string) => update((cur) => (cur.includes(tag) ? cur : [...cur, tag])),
    [update],
  );
  const unfollow = useCallback(
    (tag: string) => update((cur) => cur.filter((t) => t !== tag)),
    [update],
  );

  return { follows, followed, ready, follow, unfollow };
}
