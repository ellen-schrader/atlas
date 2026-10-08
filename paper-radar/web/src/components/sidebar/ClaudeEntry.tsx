import { NavLink } from "react-router-dom";
import { ChevronRight, Sparkles } from "lucide-react";

import { useClaudeConnection, useMcpAccess } from "@/hooks/useMcpAccess";
import { cn } from "@/lib/utils";

import { FOCUS_RING } from "./nav";

type ClaudeState = "hidden" | "connect" | "connected";

/** Always shown — it's the door to Claude, and a lab that hasn't switched it on
 *  yet needs the door most (the setup guide is where an owner turns it on).
 *  "Connected" is the member's *own* client, and only counts while the lab has
 *  access on. Hidden only for the moment it's loading, so a connected member
 *  never sees "Connect Claude" flash past first. */
function useClaudeState(teamId: string, userId: string): ClaudeState {
  const access = useMcpAccess(teamId);
  const enabled = !!access.data;
  const conn = useClaudeConnection(teamId, userId, enabled);
  if (access.isPending || (enabled && conn.isPending)) return "hidden";
  return enabled && conn.data ? "connected" : "connect";
}

function ConnectedDot() {
  return (
    <span
      aria-hidden
      className="absolute -bottom-px -right-px h-[7px] w-[7px] rounded-full bg-success ring-2 ring-surface"
    />
  );
}

/** Full-width row, pinned to the bottom of the sidebar. Both states open the
 *  setup guide; when connected it leads with the connection status. */
export function ClaudeRow({
  teamId,
  userId,
  onNavigate,
}: {
  teamId: string;
  userId: string;
  onNavigate?: () => void;
}) {
  const state = useClaudeState(teamId, userId);
  if (state === "hidden") return null;
  const connected = state === "connected";

  return (
    <NavLink
      to="/connect"
      onClick={onNavigate}
      className={cn(
        "flex items-center gap-2 rounded-control border border-border px-2.5 py-2 transition",
        "hover:border-border-strong hover:bg-surface-2",
        FOCUS_RING,
      )}
    >
      <span className="relative grid h-6 w-6 shrink-0 place-items-center text-muted">
        <Sparkles size={16} />
        {connected && <ConnectedDot />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold text-fg">
          {connected ? "Claude" : "Connect Claude"}
        </span>
        {/* Wraps rather than truncating: it fits at 232px with no room to spare,
            and a wider system font shouldn't cut off the one line of explanation. */}
        <span className="block text-xs leading-snug text-muted">
          {connected ? "Connected" : "Chat with your library"}
        </span>
      </span>
      <ChevronRight size={14} className="shrink-0 text-muted" aria-hidden />
    </NavLink>
  );
}

/** Icon-only version for the collapsed bar. */
export function ClaudeButton({ teamId, userId }: { teamId: string; userId: string }) {
  const state = useClaudeState(teamId, userId);
  if (state === "hidden") return null;
  const label = state === "connected" ? "Claude: connected" : "Connect Claude";

  return (
    <NavLink
      to="/connect"
      title={label}
      aria-label={label}
      className={cn(
        "grid h-11 w-11 place-items-center rounded-[10px] text-muted transition hover:bg-surface-2 hover:text-fg",
        FOCUS_RING,
      )}
    >
      <span className="relative grid place-items-center">
        <Sparkles size={18} />
        {state === "connected" && <ConnectedDot />}
      </span>
    </NavLink>
  );
}
