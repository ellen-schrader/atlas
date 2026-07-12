import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useProfile } from "@/hooks/useProfile";
import { supabase } from "@/lib/supabase";
import { useAppContext } from "@/routes/Layout";

export default function Settings() {
  const { team, userId } = useAppContext();
  const { data: profile } = useProfile(userId);

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-lg font-semibold">Settings</h1>
        <p className="text-sm text-muted">Your profile and lab.</p>
      </div>

      <ProfileCard userId={userId} initial={profile?.profile_md ?? ""} />

      <Card>
        <CardHeader>
          <CardTitle>Invite your lab</CardTitle>
          <CardDescription>Share this join code with lab members.</CardDescription>
        </CardHeader>
        <CardContent>
          <code className="rounded bg-surface-2 px-2 py-1 font-mono text-sm">{team.slug}</code>
        </CardContent>
      </Card>
    </div>
  );
}

function ProfileCard({ userId, initial }: { userId: string; initial: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

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
          A short description of what you work on. It personalises your paper recommendations.
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
