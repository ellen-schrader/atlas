import { type MouseEvent, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bookmark } from "lucide-react";

import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";

/** Toggles a paper on the current user's reading list (paper_status = to_read).
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
    const res = next
      ? await supabase
          .from("paper_status")
          .upsert(
            { user_id: userId, team_id: teamId, paper_id: paperId, status: "to_read" },
            { onConflict: "user_id,paper_id,team_id" },
          )
      : await supabase
          .from("paper_status")
          .delete()
          .eq("user_id", userId)
          .eq("team_id", teamId)
          .eq("paper_id", paperId)
          .eq("status", "to_read");
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
      className={cn("inline-flex items-center gap-1.5 transition", className)}
    >
      <Bookmark size={15} fill={on ? "currentColor" : "none"} />
      {showLabel && <span>{on ? "Saved" : "Save"}</span>}
    </button>
  );
}
