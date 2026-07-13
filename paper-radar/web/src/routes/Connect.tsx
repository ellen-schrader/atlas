import { type ReactNode, useState } from "react";
import { AlertTriangle, Check, ShieldAlert, X } from "lucide-react";

import { ClaudeAccessToggle, ClaudeActivity } from "@/components/ClaudeAccess";
import { CopyBlock } from "@/components/CopyBlock";
import { useMcpAccess } from "@/hooks/useMcpAccess";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/**
 * How to point Claude at this lab.
 *
 * The MCP server has existed and worked for a while with no door in the UI — the
 * one thing a user called *important* unprompted was "explaining how I can set this
 * up". So this is a setup guide, not a marketing panel: prerequisites, the real
 * config, the credentials, and a way to tell whether it worked.
 *
 * The `team_id` is pre-filled from the session, because it's the one value in the
 * whole flow that a user cannot look up or guess.
 */

type Client = "code" | "desktop";

const CLIENTS: { id: Client; label: string }[] = [
  { id: "code", label: "Claude Code" },
  { id: "desktop", label: "Claude Desktop" },
];

type Auth = "password" | "token";

export default function Connect() {
  const { team } = useAppContext();
  const [client, setClient] = useState<Client>("code");
  const [auth, setAuth] = useState<Auth>("password");

  // Claude Code runs from the repo, so a relative --directory resolves. Claude
  // Desktop does not, so it needs an absolute path or the server won't spawn.
  const dir = client === "code" ? "paper-radar" : "/absolute/path/to/paper-radar";
  const mcpJson = `{
  "mcpServers": {
    "atlas": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "${dir}",
               "--extra", "mcp", "python", "-m", "atlas_mcp"]
    }
  }
}`;

  // Two credential paths, and lab.py checks ATLAS_TOKEN *first*. A token is a
  // scoped Supabase JWT and keeps your password off disk, but it expires and the
  // stdio server has no refresh token to renew it with — so it's the safer choice
  // for a shared machine and the password is the one that keeps working. Offer both
  // and say which trade-off you're taking, rather than quietly emitting a password.
  const envPassword = `ATLAS_EMAIL=you@your-lab.org
ATLAS_PASSWORD=your-atlas-password
ATLAS_TEAM_ID=${team.id}`;
  const envToken = `ATLAS_TOKEN=your-supabase-access-token
ATLAS_TEAM_ID=${team.id}`;
  const envFile = auth === "password" ? envPassword : envToken;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <header>
        <h1 className="text-display font-serif font-semibold tracking-tight text-fg">
          Give Claude your lab’s context
        </h1>
        <p className="mt-1.5 max-w-[62ch] text-sm text-muted">
          Connect {team.name} to Claude and it can search your papers, cite them, rank them against
          your lab’s taste, and plot in your lab’s palette — instead of the field’s generic average.
          Setup is a config file and a login; it runs locally against your own database.
        </p>
      </header>

      {/* client picker — the config differs per surface */}
      <div className="flex gap-1.5">
        {CLIENTS.map((c) => (
          <button
            key={c.id}
            type="button"
            aria-pressed={client === c.id}
            onClick={() => setClient(c.id)}
            className={cn(
              "rounded-control border px-3 py-1.5 text-sm font-medium transition",
              client === c.id
                ? "border-accent bg-accent-weak text-accent"
                : "border-border text-muted hover:text-fg",
            )}
          >
            {c.label}
          </button>
        ))}
      </div>

      <Step n={1} title="Check you have uv">
        <p className="mb-2.5 text-sm text-muted">
          The server runs through{" "}
          <a
            href="https://docs.astral.sh/uv/getting-started/installation/"
            target="_blank"
            rel="noreferrer"
            className="font-medium text-accent hover:underline"
          >
            uv
          </a>
          . One line to install, no admin rights needed.
        </p>
        <CopyBlock value="uv --version" />
      </Step>

      <Step
        n={2}
        title={client === "code" ? "Add Atlas to .mcp.json" : "Add Atlas to claude_desktop_config.json"}
      >
        <p className="mb-2.5 text-sm text-muted">
          {client === "code" ? (
            <>
              In the repo root, alongside <Code>paper-radar/</Code>.
            </>
          ) : (
            <>
              Settings → Developer → Edit Config. Use an <b className="text-fg">absolute</b> path for{" "}
              <Code>--directory</Code>, since Claude Desktop doesn’t run from your repo.
            </>
          )}
        </p>
        <CopyBlock value={mcpJson} label="Copy config" />
      </Step>

      <Step n={3} title="Add your lab credentials">
        <p className="mb-2.5 text-sm text-muted">
          In <Code>paper-radar/api/.env</Code> — gitignored, and read by the server directly, so you
          never paste a credential into a Claude config file. <b className="text-fg">Your own login
          scopes the access</b>: Claude sees exactly what you see, and nothing from other labs.
        </p>

        <div className="mb-2.5 flex gap-1.5">
          {(
            [
              { id: "password", label: "Password" },
              { id: "token", label: "Access token" },
            ] as const
          ).map((a) => (
            <button
              key={a.id}
              type="button"
              aria-pressed={auth === a.id}
              onClick={() => setAuth(a.id)}
              className={cn(
                "rounded-control border px-2.5 py-1 text-xs font-medium transition",
                auth === a.id
                  ? "border-accent bg-accent-weak text-accent"
                  : "border-border text-muted hover:text-fg",
              )}
            >
              {a.label}
            </button>
          ))}
        </div>

        <p className="mb-2.5 text-xs leading-relaxed text-faint">
          {auth === "password" ? (
            <>
              Simplest, and it keeps working — the server signs in and renews itself. It does mean
              your account password sits in a file on disk.{" "}
              <b className="text-muted">On a shared or managed machine, use an access token instead.</b>
            </>
          ) : (
            <>
              Keeps your password off disk. A token is a Supabase access token (JWT) — the server
              prefers it when set.{" "}
              <b className="text-muted">
                It expires, and the local server has no refresh token, so you’ll re-paste it
                periodically.
              </b>
            </>
          )}
        </p>

        <CopyBlock value={envFile} label="Copy .env">
          {auth === "password" ? (
            <>
              <span className="text-muted">ATLAS_EMAIL=</span>you@your-lab.org{"\n"}
              <span className="text-muted">ATLAS_PASSWORD=</span>your-atlas-password{"\n"}
            </>
          ) : (
            <>
              <span className="text-muted">ATLAS_TOKEN=</span>your-supabase-access-token{"\n"}
            </>
          )}
          <span className="text-muted">ATLAS_TEAM_ID=</span>
          <span className="text-accent">{team.id}</span>{" "}
          <span className="text-faint"># {team.name} — filled in for you</span>
        </CopyBlock>
      </Step>

      <Step n={4} title="Restart Claude and check it worked" last>
        <p className="mb-2.5 text-sm text-muted">
          {client === "code" ? (
            <>
              Run <Code>/mcp</Code> — you should see <b className="text-fg">atlas</b> with its tools
              listed.
            </>
          ) : (
            <>
              Quit and reopen Claude Desktop. Atlas appears in the tools menu (the slider icon) in
              the composer.
            </>
          )}{" "}
          Then try:
        </p>
        <div className="rounded-control border border-border bg-surface-2 px-3 py-2 text-sm italic text-fg">
          “What has our lab posted on myeloid cells?”
        </div>
      </Step>

      {/* the switch — lab-wide, owner-only */}
      <AccessPanel />

      {/* what it can actually touch */}
      <section className="rounded-card border border-border bg-surface p-5">
        <h2 className="mb-3 font-serif text-lg font-semibold tracking-tight">
          What Claude can do with {team.name}
        </h2>
        <ul className="flex flex-col gap-2">
          <Perm kind="allow">
            Read papers your lab has posted — titles, abstracts, authors, venues, DOIs, tags
          </Perm>
          <Perm kind="allow">
            Read the note attached to a post, and who posted it
          </Perm>
          <Perm kind="allow">
            Read the mood board and derive your palette + a matplotlib style sheet
          </Perm>
          <Perm kind="write">
            <b className="text-fg">Post a paper</b> into the lab, optionally with a comment that
            @-mentions a teammate. This <b className="text-fg">writes to the shared lab</b> — it
            previews by default and only writes when you confirm.
          </Perm>
          <Perm kind="deny">
            Read your lab’s <b>comments or reactions</b> — the discussion stays between people
          </Perm>
          <Perm kind="deny">Anything in another lab</Perm>
          <Perm kind="deny">Delete or edit existing papers, comments, or reactions</Perm>
        </ul>

        <div className="mt-4 flex gap-2.5 rounded-control border border-danger/40 bg-danger/5 p-3">
          <ShieldAlert size={16} className="mt-0.5 shrink-0 text-danger" />
          <p className="text-xs leading-relaxed text-muted">
            <b className="text-fg">This is not one member’s decision.</b> Claude reads the lab’s
            shared corpus and can post into it, so access is a <b className="text-fg">lab-wide
            setting an owner controls</b> — and every call it makes is logged below, where the whole
            lab can see it.
          </p>
        </div>
      </section>

      <ActivityLog />

      <details className="rounded-card border border-border bg-surface p-4">
        <summary className="cursor-pointer text-sm font-semibold text-fg">It didn’t work</summary>
        <dl className="mt-3 flex flex-col gap-3 text-sm">
          <Trouble q="atlas isn’t listed">
            You’re not in the directory that holds the config, or the JSON has a trailing comma.
            In Claude Code, <Code>claude --debug</Code> prints the spawn error.
          </Trouble>
          <Trouble q="“Couldn’t sign in to your lab”">
            Wrong email or password in <Code>api/.env</Code>, or the file is in the wrong place — it
            must be <Code>paper-radar/api/.env</Code>, not the repo root.
          </Trouble>
          <Trouble q="Tools return nothing">
            You’re in more than one lab and <Code>ATLAS_TEAM_ID</Code> isn’t set. Copy it from step 3.
          </Trouble>
        </dl>
      </details>
    </div>
  );
}

/** The lab-wide switch, wrapped in Connect's section chrome. The control itself is
 *  shared with Settings, so the two screens can't drift apart. */
function AccessPanel() {
  const { team, userId } = useAppContext();
  const { data: enabled } = useMcpAccess(team.id);

  return (
    <section
      className={cn(
        "rounded-card border p-5",
        enabled ? "border-accent/40 bg-accent-weak" : "border-border bg-surface",
      )}
    >
      <ClaudeAccessToggle teamId={team.id} teamName={team.name} userId={userId} />
      {!enabled && (
        <p className="mt-3 text-xs text-faint">
          The steps above won’t work until this is on.
        </p>
      )}
    </section>
  );
}

/** The tool-call log. Visible to the whole lab — a log only the connector can read is not a check. */
function ActivityLog() {
  const { team } = useAppContext();
  return (
    <section className="rounded-card border border-border bg-surface p-5">
      <h2 className="font-serif text-lg font-semibold tracking-tight">Recent Claude activity</h2>
      <p className="mb-3 mt-1 text-sm text-muted">
        Every tool call Claude makes against {team.name}, visible to everyone in the lab. Blocked
        attempts show up here too.
      </p>
      <ClaudeActivity teamId={team.id} teamName={team.name} />
    </section>
  );
}

function Step({
  n,
  title,
  children,
  last,
}: {
  n: number;
  title: string;
  children: ReactNode;
  last?: boolean;
}) {
  return (
    <section className="flex gap-3.5">
      {/* the rail makes the sequence legible at a glance — this is a recipe, and the
          order genuinely matters */}
      <div className="flex flex-col items-center">
        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent font-mono text-xs font-bold text-accent-fg">
          {n}
        </span>
        {!last && <span className="mt-1 w-px flex-1 bg-border" aria-hidden />}
      </div>
      <div className={cn("min-w-0 flex-1", !last && "pb-5")}>
        <h2 className="mb-1.5 text-sm font-semibold text-fg">{title}</h2>
        {children}
      </div>
    </section>
  );
}

/**
 * One capability. A single `kind` rather than three booleans, so `ok + no` is not
 * representable and the icon, its colour, and the text colour all derive from one
 * source. `write` gets a genuine warning glyph — the one dangerous capability here
 * (Claude posting into the shared lab) must not rest on colour alone to be noticed.
 */
function Perm({ kind, children }: { kind: "allow" | "write" | "deny"; children: ReactNode }) {
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
