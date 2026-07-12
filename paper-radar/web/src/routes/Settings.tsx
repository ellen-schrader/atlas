import { type ReactNode, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { InviteCode } from "@/components/InviteCode";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useProfile } from "@/hooks/useProfile";
import { supabase } from "@/lib/supabase";
import { useAppContext } from "@/routes/Layout";

export default function Settings() {
  const { team, userId } = useAppContext();
  const { data: profile } = useProfile(userId);

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-8">
      <header>
        <h1 className="text-display font-bold tracking-tight">Settings</h1>
        <p className="mt-1.5 text-sm text-muted">Your profile and lab.</p>
      </header>

      <ProfilePanel userId={userId} initial={profile?.profile_md ?? ""} />

      <Panel
        title="Invite your lab"
        desc={`Share this join code — anyone who enters it joins ${team.name}.`}
      >
        <InviteCode code={team.slug} />
      </Panel>
    </div>
  );
}

function Panel({ title, desc, children }: { title: string; desc: string; children: ReactNode }) {
  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-sm">
      <h2 className="text-heading font-semibold tracking-tight">{title}</h2>
      <p className="mt-1 text-sm text-muted">{desc}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function ProfilePanel({ userId, initial }: { userId: string; initial: string }) {
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
    <Panel
      title="Your research profile"
      desc="A short description of what you work on. It personalises your paper recommendations."
    >
      <Textarea
        rows={4}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setSaved(false);
        }}
        placeholder="e.g. Oncologist working on an immunotherapy dataset focused on myeloid cells."
      />
      <div className="mt-3 flex items-center gap-3">
        <Button size="sm" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </Button>
        {saved && <span className="text-xs text-muted">Saved.</span>}
      </div>
    </Panel>
  );
}
