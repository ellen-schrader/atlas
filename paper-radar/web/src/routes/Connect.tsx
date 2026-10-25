import { type ReactNode, useState } from "react";
import { CircleCheck, PenLine } from "lucide-react";

import { ClaudeAccessToggle, ClaudeActivity, ClaudeScope } from "@/components/ClaudeAccess";
import { CopyBlock } from "@/components/CopyBlock";
import { Button } from "@/components/ui/button";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useClaudeConnection, useMcpAccess } from "@/hooks/useMcpAccess";
import { useOAuthGrants, useRevokeGrant } from "@/hooks/useOAuthGrants";
import { cn, formatDate, formatRelative } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/**
 * How to point Claude at this lab.
 *
 * The connector (a hosted MCP server, docs/CLAUDE_CONNECTOR_PLAN.md) is the whole
 * page: one URL that works in every Claude app, with nothing to install. The local
 * setup (a config file and a login on your own machine, for the tools the connector
 * doesn't offer) lives in the README; this page links to it and shows the lab id,
 * the one value in that flow a user cannot look up or guess.
 */

/** The hosted connector's address: what users paste into Claude. */
const MCP_URL = import.meta.env.VITE_MCP_URL || "https://mcp.labatlas.app/mcp";

/** The README section on running the MCP server on your own computer. */
const LOCAL_SETUP_URL = "https://github.com/ellen-schrader/atlas/blob/main/README.md#run-the-server-locally";

type App = "claude" | "code";

const APPS: { id: App; label: string }[] = [
  { id: "claude", label: "Claude app" },
  { id: "code", label: "Claude Code" },
];

export default function Connect() {
  const { team } = useAppContext();
  useDocumentTitle("Connect Claude");

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <header>
        <h1 className="text-display font-bold tracking-tight text-fg">Connect Claude</h1>
        <p className="mt-1.5 max-w-[62ch] text-sm text-muted">
          Claude can then search and cite {team.name}’s papers. Add one URL and sign in. Nothing to
          install.
        </p>
      </header>

      <ConnectionStatus />

      {/* Prerequisite, first: nothing below works until an owner turns access on. */}
      <AccessPanel />

      <ConnectorSetup />

      <ConnectedApps />

      {/* the payoff: what you can actually ask for, once connected */}
      <Capabilities />

      {/* what it can actually touch: permissions, distinct from the capabilities above */}
      <section className="rounded-card border border-border bg-surface p-5">
        <h2 className="mb-3 text-lg font-semibold tracking-tight">
          What Claude can and can’t see
        </h2>
        <ClaudeScope teamName={team.name} />
      </section>

      <ActivityLog />

      <details className="rounded-card border border-border bg-surface p-4">
        <summary className="cursor-pointer text-sm font-semibold text-fg">It didn’t work</summary>
        <dl className="mt-3 flex flex-col gap-3 text-sm">
          <Trouble q="Claude says it couldn’t connect, or keeps asking me to sign in">
            Check Claude access is on for {team.name} (above), then remove the connector in Claude
            and add it again. A connection you revoked here needs adding again too.
          </Trouble>
          <Trouble q="“Atlas didn’t recognise this app”">
            Atlas only completes sign-ins for Claude. If that came up while you were connecting
            Claude, send the address it showed to whoever runs your Atlas.
          </Trouble>
          <Trouble q="I can’t find where to add a connector">
            Custom connectors need a paid Claude plan. On a Team or Enterprise plan, an owner may
            need to add it for the organisation first (Admin settings → Connectors).
          </Trouble>
        </dl>
      </details>

      <p className="text-xs text-muted">
        Running Atlas’s server on your own computer?{" "}
        <a
          href={LOCAL_SETUP_URL}
          target="_blank"
          rel="noreferrer"
          className="font-medium text-accent hover:underline"
        >
          See the setup guide
        </a>
        . Your lab ID is <Code>{team.id}</Code>.
      </p>
    </div>
  );
}

/** The connector: one URL, and where to put it in each Claude app. */
function ConnectorSetup() {
  const [app, setApp] = useState<App>("claude");
  return (
    <section className="rounded-card border border-border bg-surface p-5">
      <h2 className="text-lg font-semibold tracking-tight">Add Atlas to Claude</h2>
      <p className="mb-1.5 mt-3 text-xs font-semibold text-muted">Connector URL</p>
      <CopyBlock value={MCP_URL} label="Copy URL" />

      <div className="mb-3 mt-4">
        <Segmented options={APPS} value={app} onChange={setApp} />
      </div>

      {app === "claude" ? (
        <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-sm text-muted">
          <li>
            In Claude (claude.ai or the desktop app), open <b className="text-fg">Settings →
            Connectors</b> and choose <b className="text-fg">Add custom connector</b>.
          </li>
          <li>
            Name it <b className="text-fg">Atlas</b>, paste the URL above, and add it.
          </li>
          <li>
            Click <b className="text-fg">Connect</b>. Atlas opens: sign in, check your lab, and
            choose <b className="text-fg">Allow</b>.
          </li>
          <li>
            Try it: ask “What has our lab posted on <span className="text-faint">[topic]</span>?”
          </li>
        </ol>
      ) : (
        <div className="flex flex-col gap-2.5 text-sm text-muted">
          <p>In a terminal, from anywhere:</p>
          <CopyBlock value={`claude mcp add --transport http atlas ${MCP_URL}`} />
          <p>
            Then in Claude Code run <Code>/mcp</Code>, pick <b className="text-fg">atlas</b> and
            choose <b className="text-fg">Authenticate</b>. Atlas opens in your browser: sign in and
            choose <b className="text-fg">Allow</b>.
          </p>
        </div>
      )}
    </section>
  );
}

/** Each Claude client that signed in through the connector, with a way to cut it off. */
function ConnectedApps() {
  const grants = useOAuthGrants();
  const revoke = useRevokeGrant();
  if (grants.error) {
    return (
      <section className="rounded-card border border-danger/40 bg-danger/5 p-5 text-sm text-muted">
        Couldn’t load your connected apps.{" "}
        <button
          type="button"
          className="font-medium text-fg underline-offset-2 hover:underline"
          onClick={() => void grants.refetch()}
        >
          Try again
        </button>
      </section>
    );
  }
  if (grants.isLoading || !grants.data?.length) return null;

  return (
    <section className="rounded-card border border-border bg-surface p-5">
      <h2 className="text-lg font-semibold tracking-tight">Your connected apps</h2>
      <p className="mb-3 mt-1 text-sm text-muted">
        Apps you’ve let use Atlas as you. Disconnecting takes effect immediately.
      </p>
      <ul className="flex flex-col divide-y divide-border">
        {grants.data.map((g) => (
          <li key={g.client.id} className="flex items-center justify-between gap-3 py-2.5">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-fg">{g.client.name || "Unnamed app"}</div>
              <div className="text-xs text-muted">Connected {formatRelative(g.granted_at)}</div>
            </div>
            <Button
              size="sm"
              variant="danger"
              disabled={revoke.isPending}
              onClick={() => revoke.mutate(g.client.id)}
            >
              Disconnect
            </Button>
          </li>
        ))}
      </ul>
      {revoke.error && (
        <p className="mt-2 text-xs text-danger">
          {revoke.error instanceof Error ? revoke.error.message : String(revoke.error)}
        </p>
      )}
    </section>
  );
}

/** Where the sidebar's "Claude · Connected" entry lands: tell the member it's
 *  working before showing them a setup guide they've already followed. */
function ConnectionStatus() {
  const { team, userId } = useAppContext();
  const { data: enabled } = useMcpAccess(team.id);
  const { data: connection } = useClaudeConnection(team.id, userId, !!enabled);
  const grants = useOAuthGrants();
  if (!enabled || !connection) return null;
  const viaConnector = (grants.data?.length ?? 0) > 0;

  return (
    <section className="flex gap-3 rounded-card border border-border bg-surface p-5">
      <CircleCheck size={18} className="mt-0.5 shrink-0 text-success" aria-hidden />
      <div className="min-w-0">
        <h2 className="text-heading font-semibold text-fg">Your Claude is connected</h2>
        <p className="mt-1 text-sm text-muted">
          Connected since {formatDate(connection.connectedAt)}, last used{" "}
          {formatRelative(connection.lastUsedAt)}. The setup steps are below if you need them on
          another computer.
        </p>
        <p className="mt-2 text-xs text-muted">
          {viaConnector ? (
            <>
              To disconnect, use <b className="text-fg">Disconnect</b> under “Your connected apps”
              below.{" "}
            </>
          ) : null}
          With the local setup, remove the <code className="font-mono">atlas</code> server from
          your Claude config to disconnect.
        </p>
      </div>
    </section>
  );
}

/** The lab-wide switch, wrapped in Connect's section chrome. The control itself is
 *  shared with Settings, so the two screens can't drift apart. */
function AccessPanel() {
  const { team, userId } = useAppContext();
  const { data: enabled, isLoading } = useMcpAccess(team.id);

  // Don't assert "off" before we know: without this the page tells a lab that HAS
  // Claude enabled that their setup won't work, then flips.
  if (isLoading) return null;

  return (
    <section
      className={cn(
        "rounded-card border p-5",
        enabled ? "border-accent/40 bg-accent-weak" : "border-border bg-surface",
      )}
    >
      <ClaudeAccessToggle
        teamId={team.id}
        teamName={team.name}
        userId={userId}
        headingLevel="h2"
      />
    </section>
  );
}

/** The tool-call log. Visible to the whole lab: a log only the connector can read is not a check. */
function ActivityLog() {
  const { team } = useAppContext();
  return (
    <section className="rounded-card border border-border bg-surface p-5">
      <h2 className="text-lg font-semibold tracking-tight">Recent Claude activity</h2>
      <p className="mb-3 mt-1 text-sm text-muted">
        Everything Claude has looked up in {team.name}. Everyone in the lab can see this.
      </p>
      <ClaudeActivity teamId={team.id} teamName={team.name} />
    </section>
  );
}

/**
 * What you can ask, grouped by the job a scientist is doing, as copy-ready
 * prompts in the lab's own voice.
 *
 * This is deliberately separate from ClaudeScope: that answers "what can Claude
 * *see*?" (permissions), this answers "what can Claude *do for me*?" (the payoff).
 * `local`: only through the local server (the README's setup); the connector reads.
 */
const CAPABILITIES: {
  group: string;
  items: { ask: string; write?: boolean; local?: boolean }[];
}[] = [
  {
    group: "Find and cite papers",
    items: [
      { ask: "What has our lab posted on myeloid cells?" },
      { ask: "Show me the abstract and DOI for that Nature paper" },
      { ask: "Find papers similar to the Wu et al. spatial atlas" },
    ],
  },
  {
    group: "Decide what to read",
    items: [
      { ask: "What should I read next?" },
      { ask: "Summarise what happened in the lab this week" },
    ],
  },
  {
    group: "Write and get unstuck",
    items: [
      { ask: "Have we already looked at CRISPR screens in exhausted T cells?" },
      { ask: "Draft a related-work paragraph on spatial transcriptomics from our papers" },
      { ask: "Add this arXiv paper and tag Maya to read it", write: true, local: true },
    ],
  },
  {
    group: "Plot in your lab’s style",
    items: [
      { ask: "Give me a matplotlib style that matches our lab’s figures", local: true },
      { ask: "Is this figure’s colour palette safe for colourblind readers?", local: true },
    ],
  },
];

function Capabilities() {
  return (
    <section className="rounded-card border border-border bg-surface p-5">
      <h2 className="mb-4 text-lg font-semibold tracking-tight">Things to ask</h2>
      <div className="flex flex-col gap-5">
        {CAPABILITIES.map((section) => (
          <div key={section.group}>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">
              {section.group}
            </h3>
            <ul className="flex flex-col gap-2">
              {section.items.map((item) => (
                <li key={item.ask} className="flex items-baseline gap-1.5 text-sm">
                  {item.write && (
                    <PenLine size={13} className="translate-y-0.5 shrink-0 text-danger" aria-label="Adds to the lab" />
                  )}
                  <span className="italic text-fg">“{item.ask}”</span>
                  {item.local && <span className="shrink-0 text-xs text-faint">(local setup)</span>}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <p className="mt-4 flex items-center gap-1.5 text-xs text-faint">
        <PenLine size={12} className="shrink-0 text-danger" aria-hidden />
        Adds to the shared lab. Claude shows a preview and only adds it when you confirm.
      </p>
      <p className="mt-1 text-xs text-faint">
        (local setup): needs Atlas’s server on your own computer. The connector only reads.
      </p>
    </section>
  );
}

/** A row of mutually exclusive buttons (the app pickers). */
function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="flex gap-1.5">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={value === o.id}
          onClick={() => onChange(o.id)}
          className={cn(
            "rounded-control border px-3 py-1.5 text-sm font-medium transition",
            value === o.id
              ? "border-accent bg-accent-weak text-accent"
              : "border-border text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Trouble({ q, children }: { q: string; children: ReactNode }) {
  return (
    <div>
      <dt className="font-medium text-fg">{q}</dt>
      <dd className="mt-0.5 text-muted">{children}</dd>
    </div>
  );
}

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.85em] text-accent">
      {children}
    </code>
  );
}
