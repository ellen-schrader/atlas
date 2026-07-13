import { Check, X } from "lucide-react";

import { useMcpAccess, useMcpToolCalls, useSetMcpAccess } from "@/hooks/useMcpAccess";
import { useMyRole } from "@/hooks/useMyRole";
import { cn, formatRelative } from "@/lib/utils";

/**
 * The lab-wide Claude access switch, and the log of what Claude did with it.
 *
 * Lives here rather than inside Connect because it belongs in two places: Connect,
 * where you're setting the integration up, and Settings, where anyone looking for
 * "what can Claude see of my lab?" will actually go. Same component, one source of
 * truth for the copy and the permission checks.
 */

export function ClaudeAccessToggle({ teamId, teamName, userId }: Props) {
  const { data: role } = useMyRole(teamId, userId);
  const { data: enabled, isLoading } = useMcpAccess(teamId);
  const setAccess = useSetMcpAccess(teamId);
  const isOwner = role === "owner";

  if (isLoading) return null;

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-fg">
            <span
              className={cn(
                "inline-block h-2 w-2 shrink-0 rounded-full",
                enabled ? "bg-accent" : "bg-faint",
              )}
            />
            {enabled ? "Claude access is on" : "Claude access is off"}
          </p>
          <p className="mt-1 max-w-[54ch] text-sm text-muted">
            {enabled
              ? `Claude can read ${teamName}'s papers and post into it. Every call is logged.`
              : `Atlas refuses every Claude tool call for ${teamName} while this is off.`}
          </p>
        </div>

        <button
          type="button"
          disabled={!isOwner || setAccess.isPending}
          onClick={() => setAccess.mutate(!enabled)}
          title={isOwner ? undefined : "Only a lab owner can change this"}
          className={cn(
            "shrink-0 rounded-control px-3.5 py-2 text-sm font-semibold transition",
            !isOwner && "cursor-not-allowed opacity-50",
            enabled
              ? "border border-border-strong bg-surface text-fg hover:border-danger hover:text-danger"
              : "bg-accent text-accent-fg hover:brightness-110",
          )}
        >
          {setAccess.isPending ? "…" : enabled ? "Turn off" : "Turn on for the lab"}
        </button>
      </div>

      {!isOwner && (
        <p className="mt-3 text-xs text-faint">
          Only an owner of {teamName} can change this. Ask one to turn it on.
        </p>
      )}
      {setAccess.isError && (
        <p className="mt-3 text-xs text-danger">
          Couldn’t change access — {(setAccess.error as Error).message}
        </p>
      )}
    </div>
  );
}

/** What Claude can and can't see. Stated once, so the two screens can't drift apart. */
export function ClaudeScope() {
  return (
    <ul className="flex flex-col gap-1.5">
      <Line kind="allow">Papers your lab has posted, and the note attached to a post</Line>
      <Line kind="allow">The mood board, and the palette derived from it</Line>
      <Line kind="deny">
        Your lab’s <strong className="font-semibold">comments and reactions</strong> — the discussion
        stays between people
      </Line>
      <Line kind="deny">Anything in another lab</Line>
    </ul>
  );
}

/** The tool-call log — visible to every member, not just whoever connected. */
export function ClaudeActivity({ teamId, teamName, limit = 8 }: { teamId: string; teamName: string; limit?: number }) {
  const { data: calls, isLoading } = useMcpToolCalls(teamId, limit);

  if (isLoading) return <p className="text-sm text-faint">Loading…</p>;

  if (!calls?.length) {
    return (
      <p className="rounded-control border border-dashed border-border px-3 py-5 text-center text-sm text-faint">
        Claude hasn’t used {teamName} yet.
      </p>
    );
  }

  return (
    <ul className="flex flex-col divide-y divide-border">
      {calls.map((c) => (
        <li key={c.id} className="flex items-center gap-3 py-2 text-sm">
          {c.ok ? (
            <Check size={14} className="shrink-0 text-accent" />
          ) : (
            <X size={14} className="shrink-0 text-danger" />
          )}
          <code className="min-w-0 flex-1 truncate font-mono text-xs text-fg">{c.tool}</code>
          {!c.ok && <span className="shrink-0 text-xs text-danger">blocked</span>}
          <span className="shrink-0 font-mono text-xs text-faint">
            {formatRelative(c.called_at)}
          </span>
        </li>
      ))}
    </ul>
  );
}

interface Props {
  teamId: string;
  teamName: string;
  userId: string;
}

function Line({ kind, children }: { kind: "allow" | "deny"; children: React.ReactNode }) {
  return (
    <li className="flex gap-2.5 text-sm">
      <span className="mt-0.5 shrink-0">
        {kind === "allow" ? (
          <Check size={14} className="text-accent" />
        ) : (
          <X size={14} className="text-faint" />
        )}
      </span>
      <span className={cn("leading-relaxed", kind === "deny" ? "text-faint" : "text-muted")}>
        {children}
      </span>
    </li>
  );
}
