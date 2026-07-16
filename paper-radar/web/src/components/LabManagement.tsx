import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Crown, LogOut } from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { InviteCode } from "@/components/InviteCode";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useMembers } from "@/hooks/useMembers";
import { useMyRole } from "@/hooks/useMyRole";
import {
  deleteTeamsIntegration,
  getTeamsIntegration,
  saveTeamsIntegration,
  testTeamsIntegration,
} from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";

function Panel({ title, desc, children }: { title: string; desc: string; children: ReactNode }) {
  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-sm">
      <h2 className="text-heading font-semibold tracking-tight">{title}</h2>
      <p className="mt-1 text-sm text-muted">{desc}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function hostOf(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

/** Owner-only: connect the lab to a Teams channel via a Power Automate webhook.
 *  The webhook URL is write-only from a member's perspective (owner-only RLS) and
 *  is validated server-side; this panel never posts to it directly — the test
 *  card goes through the API so the URL stays server-side at send time. */
function TeamsPanel({ teamId }: { teamId: string }) {
  const qc = useQueryClient();
  const { data: teams } = useQuery({
    queryKey: ["teams-integration", teamId],
    queryFn: () => getTeamsIntegration(teamId),
  });
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  async function run(key: string, fn: () => Promise<unknown>, okText?: string) {
    setBusy(key);
    setNotice(null);
    try {
      await fn();
      if (okText) setNotice({ ok: true, text: okText });
      void qc.invalidateQueries({ queryKey: ["teams-integration", teamId] });
      return true;
    } catch (e) {
      setNotice({ ok: false, text: e instanceof Error ? e.message : "Something went wrong." });
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function connect(e: FormEvent) {
    e.preventDefault();
    if (
      await run("save", () => saveTeamsIntegration(teamId, url.trim()), "Connected. Send a test card to confirm it works.")
    )
      setUrl("");
  }

  const host = hostOf(teams?.webhook_url ?? null);

  return (
    <Panel title="Post to Teams" desc="Mirror new papers into a Microsoft Teams channel.">
      {teams?.configured ? (
        <div className="flex flex-col gap-3 text-sm">
          <div>
            Connected{host && (
              <>
                {" "}to <span className="font-medium">{host}</span>
              </>
            )}
            {!teams.enabled && <span className="text-muted"> (paused)</span>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => run("test", () => testTeamsIntegration(teamId), "Test card sent — check the channel.")}
              disabled={busy !== null || !teams.enabled}
            >
              {busy === "test" ? "…" : "Send test card"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                teams.webhook_url &&
                run("toggle", () => saveTeamsIntegration(teamId, teams.webhook_url as string, !teams.enabled))
              }
              disabled={busy !== null}
            >
              {busy === "toggle" ? "…" : teams.enabled ? "Pause" : "Resume"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-danger hover:text-danger"
              onClick={() => run("rm", () => deleteTeamsIntegration(teamId), "Disconnected.")}
              disabled={busy !== null}
            >
              {busy === "rm" ? "…" : "Disconnect"}
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={connect} className="flex flex-col gap-2">
          <ol className="list-decimal pl-4 text-xs text-muted [&>li]:mt-0.5">
            <li>
              In Teams, open <span className="font-medium">Workflows</span> and create a flow from
              the “Send webhook alerts to a channel” template.
            </li>
            <li>Pick the team and channel new papers should appear in.</li>
            <li>Copy the webhook URL the flow generates and paste it here.</li>
          </ol>
          <Label htmlFor="teams-webhook">Webhook URL</Label>
          <div className="flex gap-2">
            <Input
              id="teams-webhook"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://…logic.azure.com/workflows/…"
            />
            <Button type="submit" size="sm" disabled={busy === "save" || !url.trim()}>
              {busy === "save" ? "…" : "Connect"}
            </Button>
          </div>
        </form>
      )}
      {notice && (
        <p className={cn("mt-3 text-xs", notice.ok ? "text-muted" : "text-danger")}>
          {notice.text}
        </p>
      )}
    </Panel>
  );
}

function RoleBadge({ role }: { role: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize",
        role === "owner" ? "bg-accent-weak text-accent" : "bg-surface-2 text-muted",
      )}
    >
      {role === "owner" && <Crown size={11} />}
      {role}
    </span>
  );
}

export function LabManagement({
  teamId,
  teamName,
  teamCode,
  userId,
}: {
  teamId: string;
  teamName: string;
  teamCode: string;
  userId: string;
}) {
  const qc = useQueryClient();
  const { data: role } = useMyRole(teamId, userId);
  const isOwner = role === "owner";
  const { data: members } = useMembers(teamId);

  const [name, setName] = useState(teamName);
  useEffect(() => setName(teamName), [teamName]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);

  async function call(key: string, fn: () => PromiseLike<{ error: { message: string } | null }>) {
    setBusy(key);
    setErr(null);
    const { error } = await fn();
    setBusy(null);
    if (error) setErr(error.message);
    return !error;
  }
  const refreshTeam = () => void qc.invalidateQueries({ queryKey: ["memberships"] });
  const refreshMembers = () => {
    void qc.invalidateQueries({ queryKey: ["members", teamId] });
    void qc.invalidateQueries({ queryKey: ["my-role", teamId] });
  };

  async function rename(e: FormEvent) {
    e.preventDefault();
    if (await call("rename", () => supabase.rpc("rename_team", { p_team: teamId, p_name: name.trim() })))
      refreshTeam();
  }
  async function regenerate() {
    if (await call("regen", () => supabase.rpc("regenerate_team_code", { p_team: teamId }))) refreshTeam();
  }
  async function setRole(uid: string, r: "owner" | "member") {
    if (await call(`role-${uid}`, () => supabase.rpc("set_member_role", { p_team: teamId, p_user: uid, p_role: r })))
      refreshMembers();
  }
  async function remove(uid: string) {
    if (await call(`rm-${uid}`, () => supabase.rpc("remove_member", { p_team: teamId, p_user: uid })))
      refreshMembers();
  }
  async function leave() {
    if (await call("leave", () => supabase.rpc("leave_team", { p_team: teamId }))) refreshTeam();
  }

  return (
    <>
      <Panel title="Lab" desc="Your lab’s name and join code.">
        {isOwner ? (
          <form onSubmit={rename} className="flex flex-col gap-1.5">
            <Label htmlFor="lab-name">Lab name</Label>
            <div className="flex gap-2">
              <Input id="lab-name" value={name} onChange={(e) => setName(e.target.value)} />
              <Button type="submit" size="sm" disabled={busy === "rename" || !name.trim() || name.trim() === teamName}>
                {busy === "rename" ? "…" : "Save"}
              </Button>
            </div>
          </form>
        ) : (
          <div className="text-sm font-medium">{teamName}</div>
        )}

        <div className="mt-4">
          <Label>Join code</Label>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <InviteCode code={teamCode} />
            {isOwner && (
              <Button variant="secondary" size="sm" onClick={regenerate} disabled={busy === "regen"}>
                {busy === "regen" ? "…" : "Regenerate"}
              </Button>
            )}
          </div>
          {isOwner && (
            <p className="mt-1.5 text-xs text-muted">Regenerating invalidates the current code.</p>
          )}
        </div>
      </Panel>

      <Panel title="Members" desc={`${members?.length ?? 0} ${(members?.length ?? 0) === 1 ? "person" : "people"} in ${teamName}.`}>
        <div className="flex flex-col divide-y divide-border">
          {(members ?? []).map((m) => (
            <div key={m.user_id} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
              <Avatar name={m.profiles?.display_name ?? "?"} size={30} />
              <div className="min-w-0 flex-1 text-sm font-medium">
                {m.profiles?.display_name ?? "Someone"}
                {m.user_id === userId && <span className="font-normal text-muted"> (you)</span>}
              </div>
              <RoleBadge role={m.role} />
              {isOwner && m.user_id !== userId && (
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy === `role-${m.user_id}`}
                    onClick={() => setRole(m.user_id, m.role === "owner" ? "member" : "owner")}
                  >
                    {m.role === "owner" ? "Make member" : "Make owner"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-danger hover:text-danger"
                    disabled={busy === `rm-${m.user_id}`}
                    onClick={() => remove(m.user_id)}
                  >
                    Remove
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
        {err && <p className="mt-3 text-xs text-danger">{err}</p>}
      </Panel>

      {isOwner && <TeamsPanel teamId={teamId} />}

      <Panel title="Leave lab" desc="You’ll lose access to this lab’s papers and discussions.">
        {!leaving ? (
          <Button variant="secondary" size="sm" className="text-danger" onClick={() => setLeaving(true)}>
            <LogOut size={14} /> Leave {teamName}
          </Button>
        ) : (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>Leave {teamName}?</span>
            <Button size="sm" variant="danger" onClick={leave} disabled={busy === "leave"}>
              {busy === "leave" ? "…" : "Leave"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setLeaving(false)}>
              Cancel
            </Button>
            {err && <span className="text-xs text-danger">{err}</span>}
          </div>
        )}
      </Panel>
    </>
  );
}
