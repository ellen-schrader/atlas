import { type MouseEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bookmark } from "lucide-react";

import { deleteIfDefault } from "@/lib/paperStatus";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";

/** Toggles `paper_status.saved` — "this one is mine": on my reading list, and
 *  the strongest taste signal there is (1.5x in the API's taste vector). It is
 *  deliberately independent of reading progress, so a paper central to your
 *  project stays saved after you have read it.
 *
 *  Optimistic: flips immediately, reverts on error, and refreshes the reading
 *  list (which the dashboard + card bookmark states read from). */
export function BookmarkButton({
  paperId,
  teamId,
  userId,
  bookmarked,
  showLabel = false,
  className,
}: {
  paperId: string;
  teamId: string;
  userId: string;
  bookmarked: boolean;
  showLabel?: boolean;
  className?: string;
}) {
  const qc = useQueryClient();
  const [on, setOn] = useState(bookmarked);
  const [busy, setBusy] = useState(false);

  useEffect(() => setOn(bookmarked), [bookmarked]);

  async function toggle(e: MouseEvent) {
    e.stopPropagation();
    if (busy) return;
    const next = !on;
    setOn(next);
    setBusy(true);
    // The payload carries `saved` only, so an existing row keeps whatever
    // progress it has; a new row takes the 'unread' column default.
    const res = next
      ? await supabase
          .from("paper_status")
          .upsert(
            { user_id: userId, team_id: teamId, paper_id: paperId, saved: true },
            { onConflict: "user_id,paper_id,team_id" },
          )
      : await supabase
          .from("paper_status")
          .update({ saved: false })
          .eq("user_id", userId)
          .eq("team_id", teamId)
          .eq("paper_id", paperId);
    // Un-saving a paper with no progress leaves an all-default row, and
    // recommend_v2 excludes every paper that has ANY row — so the paper would
    // vanish from Discover instead of returning to it.
    if (!next && !res.error) await deleteIfDefault(supabase, userId, teamId, paperId);
    setBusy(false);
    if (res.error) {
      setOn(!next); // revert
      return;
    }
    void qc.invalidateQueries({ queryKey: ["reading-list", userId, teamId] });
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={on}
      aria-label={on ? "Remove from reading list" : "Save to reading list"}
      // A deliberate save is the heaviest taste signal there is (1.5x in `_taste_vector`).
      title={on ? "Saved — the strongest signal of your lab’s taste" : "Save — the strongest signal of your lab’s taste"}
      className={cn("inline-flex items-center gap-1.5 transition", className)}
    >
      <Bookmark size={15} fill={on ? "currentColor" : "none"} />
      {showLabel && <span>{on ? "Saved" : "Save"}</span>}
    </button>
  );
}
