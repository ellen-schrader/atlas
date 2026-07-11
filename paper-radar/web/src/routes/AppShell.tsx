import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { useQueryClient } from "@tanstack/react-query";
import { LogOut, Users } from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { Brand } from "@/components/Brand";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useProfile } from "@/hooks/useProfile";
import { supabase } from "@/lib/supabase";
import type { Membership } from "@/lib/types";

export default function AppShell({
  session,
  memberships,
}: {
  session: Session;
  memberships: Membership[];
}) {
  const team = memberships[0]?.teams;
  const { data: profile } = useProfile(session.user.id);
  const displayName = profile?.display_name ?? session.user.email ?? "You";

  return (
    <div className="flex min-h-full">
      <aside className="flex w-64 shrink-0 flex-col gap-4 border-r border-border bg-surface p-4">
        <Brand />
        <div className="flex items-center gap-2.5 rounded-md border border-border bg-surface-2 p-2.5">
          <Avatar name={displayName} size={34} />
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">{displayName}</div>
            {team && (
              <div className="flex items-center gap-1 text-xs text-muted">
                <Users size={12} />
                {team.name}
              </div>
            )}
          </div>
        </div>
        <div className="mt-auto flex items-center justify-between">
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={() => supabase.auth.signOut()}>
            <LogOut size={14} /> Log out
          </Button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
          <div>
            <h1 className="text-lg font-semibold">Papers</h1>
            <p className="text-sm text-muted">
              Ingest, search, and discovery land here next. For now, set up your profile below.
            </p>
          </div>

          {team && (
            <Card>
              <CardHeader>
                <CardTitle>Invite your lab</CardTitle>
                <CardDescription>Share this join code with lab members.</CardDescription>
              </CardHeader>
              <CardContent>
                <code className="rounded bg-surface-2 px-2 py-1 font-mono text-sm">{team.slug}</code>
              </CardContent>
            </Card>
          )}

          <ProfileCard userId={session.user.id} initial={profile?.profile_md ?? ""} />
        </div>
      </main>
    </div>
  );
}

function ProfileCard({ userId, initial }: { userId: string; initial: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  // Sync once the profile query resolves.
  useEffect(() => setText(initial), [initial]);

  async function save() {
    setBusy(true);
    setSaved(false);
    const { error } = await supabase.from("profiles").update({ profile_md: text }).eq("id", userId);
    setBusy(false);
    if (!error) {
      setSaved(true);
      await qc.invalidateQueries({ queryKey: ["profile", userId] });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your profile (USER.md)</CardTitle>
        <CardDescription>
          A short description of what you work on. It will personalise your paper recommendations.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col items-start gap-3">
        <Textarea
          rows={4}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setSaved(false);
          }}
          placeholder="e.g. Oncologist working on an immunotherapy dataset focused on myeloid cells."
        />
        <div className="flex items-center gap-3">
          <Button size="sm" onClick={save} disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </Button>
          {saved && <span className="text-xs text-muted">Saved.</span>}
        </div>
      </CardContent>
    </Card>
  );
}
