import { type ReactNode } from "react";
import { AlertTriangle, Check, X } from "lucide-react";

import { useMcpAccess, useMcpToolCalls, useSetMcpAccess } from "@/hooks/useMcpAccess";
import { useMyRole } from "@/hooks/useMyRole";
import { cn, formatRelative } from "@/lib/utils";

/**
 * The lab-wide Claude access switch, what it grants, and the log of what Claude did
 * with it.
 *
 * All three live here rather than inside Connect because they belong in two places:
 * Connect, where you set the integration up, and Settings, where anyone asking "what
 * can Claude see of my lab?" will actually go. One source of truth — the app must
 * never make two different privacy promises about the same server, which is exactly
 * what happens when the capabilities change (as they did when `post_paper` landed and
 * made the old "read-only" copy false) and only one copy of the list gets updated.
 */

export function ClaudeAccessToggle({ teamId, teamName, userId, headingLevel = "p" }: Props) {
  const Heading = headingLevel;
  const { data: role } = useMyRole(teamId, userId);
  const { data: enabled, isLoading } = useMcpAccess(teamId);
  const setAccess = useSetMcpAccess(teamId);
  const isOwner = role === "owner";

  if (isLoading) return null;

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Heading
            className={cn(
              "flex items-center gap-2 text-fg",
              headingLevel === "h2"
                ? "font-serif text-lg font-semibold tracking-tight"
                : "text-sm font-semibold",
            )}
          >
            <span
              className={cn(
                "inline-block h-2 w-2 shrink-0 rounded-full",
                enabled ? "bg-accent" : "bg-faint",
              )}
            />
            {enabled ? "Claude access is on" : "Claude access is off"}
          </Heading>
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

/**
 * What Claude can and cannot do with the lab. THE statement of scope — Connect and
 * Settings both render this, so the app cannot promise two different things.
 */
export function ClaudeScope({ teamName }: { teamName: string }) {
  return (
    <ul className="flex flex-col gap-2">
      <Line kind="allow">
        Read papers your lab has posted — titles, abstracts, authors, venues, DOIs, tags
      </Line>
      <Line kind="allow">Read the note attached to a post, and who posted it</Line>
      <Line kind="allow">
        Read the mood board and derive your palette + a matplotlib style sheet
      </Line>
      <Line kind="write">
        <strong className="font-semibold text-fg">Post a paper</strong> into {teamName}, optionally
        with a comment that @-mentions a teammate. This{" "}
        <strong className="font-semibold text-fg">writes to the shared lab</strong> — it previews by
        default and only writes when you confirm.
      </Line>
      <Line kind="deny">
        Read your lab’s <strong className="font-semibold">comments or reactions</strong> — the
        discussion stays between people
      </Line>
      <Line kind="deny">Anything in another lab</Line>
      <Line kind="deny">Delete or edit existing papers, comments, or reactions</Line>
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
  /** "h2" where this is a page section (Connect); "p" inside a Panel that already
   *  owns the heading (Settings). Without this the switch is either invisible to a
   *  screen reader navigating by heading, or it duplicates its container's heading. */
  headingLevel?: "h2" | "p";
}

/** The one capability that can change the lab gets a warning glyph, not just a colour. */
function Line({ kind, children }: { kind: "allow" | "write" | "deny"; children: ReactNode }) {
  const icon = {
    allow: <Check size={15} className="text-accent" />,
    write: <AlertTriangle size={15} className="text-danger" />,
    deny: <X size={15} className="text-faint" />,
  }[kind];

  return (
    <li className="flex gap-2.5 text-sm">
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span className={cn("leading-relaxed", kind === "deny" ? "text-faint" : "text-muted")}>
        {children}
      </span>
    </li>
  );
}
