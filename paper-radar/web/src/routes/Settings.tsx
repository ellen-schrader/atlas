import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { ClaudeAccessToggle, ClaudeActivity, ClaudeScope } from "@/components/ClaudeAccess";
import { LabManagement } from "@/components/LabManagement";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useProfile } from "@/hooks/useProfile";
import { updateProfile } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

type Note = { ok: boolean; text: string } | null;

export default function Settings() {
  const { team, userId, session } = useAppContext();
  const { data: profile } = useProfile(userId);

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-8">
      <header>
        <h1 className="text-display font-serif font-semibold tracking-tight">Settings</h1>
        <p className="mt-1.5 text-sm text-muted">Your account, profile, and lab.</p>
      </header>

      <AccountPanel
        userId={userId}
        currentName={profile?.display_name ?? ""}
        currentEmail={session.user.email ?? ""}
      />

      <ProfilePanel userId={userId} initial={profile?.profile_md ?? ""} />

      <ClaudePrivacyPanel teamId={team.id} teamName={team.name} userId={userId} />

      <LabManagement teamId={team.id} teamName={team.name} teamSlug={team.slug} userId={userId} />
    </div>
  );
}

/**
 * Claude access, in Settings as well as on Connect.
 *
 * Connect is where you *set the integration up*; this is where someone goes when the
 * question is "what can Claude see of my lab, and who decided that?" — which is a
 * privacy question, and privacy questions get answered in Settings. The control and
 * the scope copy are shared with Connect, so the two screens can't tell different
 * stories.
 */
function ClaudePrivacyPanel({
  teamId,
  teamName,
  userId,
}: {
  teamId: string;
  teamName: string;
  userId: string;
}) {
  return (
    <Panel
      title="Claude access"
      desc={`Whether Claude can read ${teamName} — and what it can see when it does.`}
    >
      <div className="mt-4 flex flex-col gap-5">
        <ClaudeAccessToggle teamId={teamId} teamName={teamName} userId={userId} />

        <div className="border-t border-border pt-4">
          <h3 className="text-eyebrow font-bold uppercase tracking-eyebrow text-muted">
            What Claude can see
          </h3>
          <div className="mt-2.5">
            <ClaudeScope teamName={teamName} />
          </div>
          <p className="mt-3 text-xs leading-relaxed text-faint">
            Access is lab-wide and owner-controlled, because it isn’t one member’s call.
          </p>
        </div>

        <div className="border-t border-border pt-4">
          <div className="mb-2.5 flex items-center justify-between gap-3">
            <h3 className="text-eyebrow font-bold uppercase tracking-eyebrow text-muted">
              Recent Claude activity
            </h3>
            <Link to="/connect" className="text-xs font-medium text-accent hover:underline">
              Set up Claude →
            </Link>
          </div>
          <ClaudeActivity teamId={teamId} teamName={teamName} limit={5} />
        </div>
      </div>
    </Panel>
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

function FieldNote({ note }: { note: Note }) {
  if (!note) return null;
  return <p className={cn("mt-1.5 text-xs", note.ok ? "text-accent" : "text-danger")}>{note.text}</p>;
}

function AccountPanel({
  userId,
  currentName,
  currentEmail,
}: {
  userId: string;
  currentName: string;
  currentEmail: string;
}) {
  const qc = useQueryClient();

  const [name, setName] = useState(currentName);
  const [nameBusy, setNameBusy] = useState(false);
  const [nameNote, setNameNote] = useState<Note>(null);
  useEffect(() => setName(currentName), [currentName]);

  const [email, setEmail] = useState(currentEmail);
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailNote, setEmailNote] = useState<Note>(null);
  useEffect(() => setEmail(currentEmail), [currentEmail]);

  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const [pwNote, setPwNote] = useState<Note>(null);

  async function saveName(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || name.trim() === currentName) return;
    setNameBusy(true);
    setNameNote(null);
    const { error } = await supabase.from("profiles").update({ display_name: name.trim() }).eq("id", userId);
    // keep the auth metadata in sync (best effort — the app reads profiles)
    await supabase.auth.updateUser({ data: { display_name: name.trim() } });
    setNameBusy(false);
    if (error) setNameNote({ ok: false, text: error.message });
    else {
      setNameNote({ ok: true, text: "Saved." });
      await qc.invalidateQueries({ queryKey: ["profile", userId] });
    }
  }

  async function saveEmail(e: FormEvent) {
    e.preventDefault();
    if (!email.trim() || email.trim() === currentEmail) return;
    setEmailBusy(true);
    setEmailNote(null);
    const { error } = await supabase.auth.updateUser({ email: email.trim() });
    setEmailBusy(false);
    if (error) setEmailNote({ ok: false, text: error.message });
    else setEmailNote({ ok: true, text: "Check your new email to confirm the change." });
  }

  async function savePassword(e: FormEvent) {
    e.preventDefault();
    setPwNote(null);
    if (pw.length < 8) {
      setPwNote({ ok: false, text: "Password must be at least 8 characters." });
      return;
    }
    if (pw !== pw2) {
      setPwNote({ ok: false, text: "Passwords don’t match." });
      return;
    }
    setPwBusy(true);
    const { error } = await supabase.auth.updateUser({ password: pw });
    setPwBusy(false);
    if (error) setPwNote({ ok: false, text: error.message });
    else {
      setPwNote({ ok: true, text: "Password updated." });
      setPw("");
      setPw2("");
    }
  }

  return (
    <Panel title="Account" desc="Your name, email, and password.">
      <div className="flex flex-col gap-6">
        <form onSubmit={saveName} className="flex flex-col gap-1.5">
          <Label htmlFor="acct-name">Display name</Label>
          <div className="flex gap-2">
            <Input
              id="acct-name"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setNameNote(null);
              }}
            />
            <Button
              type="submit"
              size="sm"
              disabled={nameBusy || !name.trim() || name.trim() === currentName}
            >
              {nameBusy ? "…" : "Save"}
            </Button>
          </div>
          <FieldNote note={nameNote} />
        </form>

        <form onSubmit={saveEmail} className="flex flex-col gap-1.5">
          <Label htmlFor="acct-email">Email</Label>
          <div className="flex gap-2">
            <Input
              id="acct-email"
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setEmailNote(null);
              }}
            />
            <Button
              type="submit"
              size="sm"
              disabled={emailBusy || !email.trim() || email.trim() === currentEmail}
            >
              {emailBusy ? "…" : "Update"}
            </Button>
          </div>
          <FieldNote note={emailNote} />
        </form>

        <form onSubmit={savePassword} className="flex flex-col gap-1.5">
          <Label htmlFor="acct-pw">New password</Label>
          <Input
            id="acct-pw"
            type="password"
            value={pw}
            onChange={(e) => {
              setPw(e.target.value);
              setPwNote(null);
            }}
            placeholder="At least 8 characters"
            autoComplete="new-password"
          />
          <Label htmlFor="acct-pw2" className="mt-1.5">
            Confirm new password
          </Label>
          <Input
            id="acct-pw2"
            type="password"
            value={pw2}
            onChange={(e) => {
              setPw2(e.target.value);
              setPwNote(null);
            }}
            autoComplete="new-password"
          />
          <div className="mt-2">
            <Button type="submit" size="sm" disabled={pwBusy || !pw || !pw2}>
              {pwBusy ? "…" : "Update password"}
            </Button>
          </div>
          <FieldNote note={pwNote} />
        </form>
      </div>
    </Panel>
  );
}

function ProfilePanel({ userId, initial }: { userId: string; initial: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setText(initial), [initial]);

  async function save() {
    setBusy(true);
    setSaved(false);
    setError(null);
    try {
      // Save + re-embed via the API so profile_vec stays in sync with the text
      // (recommendations rank against it). The service holds the embedding key.
      await updateProfile(text);
      setSaved(true);
      await qc.invalidateQueries({ queryKey: ["profile", userId] });
      await qc.invalidateQueries({ queryKey: ["recommendations"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
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
        {error && <span className="text-xs text-danger">{error}</span>}
      </div>
    </Panel>
  );
}
