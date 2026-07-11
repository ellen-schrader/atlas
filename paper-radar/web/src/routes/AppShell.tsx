import { type FormEvent, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { useQueryClient } from "@tanstack/react-query";
import { LogOut, Users } from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { Brand } from "@/components/Brand";
import { PaperEngagement } from "@/components/Engagement";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Textarea } from "@/components/ui/textarea";
import { usePapers } from "@/hooks/usePapers";
import { useProfile } from "@/hooks/useProfile";
import { postPaper } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import type { Membership, PaperPost } from "@/lib/types";
import { formatAuthors, formatDate } from "@/lib/utils";

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
              Papers your lab has posted. Search and discovery land here next.
            </p>
          </div>

          {team && <PostPaperCard teamId={team.id} />}
          {team && <PaperFeed teamId={team.id} userId={session.user.id} />}

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

function PostPaperCard({ teamId }: { teamId: string }) {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await postPaper(url.trim(), teamId);
      const title = r.paper.title ?? r.paper.url;
      setResult((r.already_posted ? "Already in your lab: " : "Posted: ") + title);
      setUrl("");
      await qc.invalidateQueries({ queryKey: ["papers", teamId] });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Post a paper</CardTitle>
        <CardDescription>Paste a paper URL — arXiv, DOI, PubMed, or a publisher page.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="flex gap-2">
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://arxiv.org/abs/…"
            required
          />
          <Button type="submit" disabled={busy || !url.trim()}>
            {busy ? "…" : "Post"}
          </Button>
        </form>
        {result && <p className="mt-2 text-xs text-muted">{result}</p>}
        {error && <p className="mt-2 text-xs text-danger">{error}</p>}
      </CardContent>
    </Card>
  );
}

function paperMatches(post: PaperPost, q: string): boolean {
  if (!q) return true;
  const p = post.papers;
  const hay = [p.title, p.venue, p.abstract, p.authors.join(" "), p.tags.join(" "), p.keywords.join(" ")]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return hay.includes(q.toLowerCase());
}

function PaperFeed({ teamId, userId }: { teamId: string; userId: string }) {
  const { data, isLoading, error } = usePapers(teamId);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<PaperPost | null>(null);

  if (isLoading) return <p className="text-sm text-muted">Loading papers…</p>;
  if (error) return <p className="text-sm text-danger">Couldn’t load papers.</p>;

  const posts = data ?? [];
  if (posts.length === 0) {
    return <p className="text-sm text-muted">No papers yet — post one above.</p>;
  }

  const filtered = posts.filter((p) => paperMatches(p, query.trim()));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search title, author, abstract, tag…"
          className="max-w-xs"
        />
        <span className="text-xs text-muted">
          {filtered.length} of {posts.length}
        </span>
      </div>

      {filtered.length === 0 ? (
        <p className="text-sm text-muted">No papers match “{query}”.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-2.5 font-medium">Title</th>
                <th className="px-4 py-2.5 font-medium">Authors</th>
                <th className="px-4 py-2.5 font-medium">Posted</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => (
                <tr
                  key={p.id}
                  onClick={() => setSelected(p)}
                  className="cursor-pointer border-b border-border align-top last:border-0 hover:bg-surface-2"
                >
                  <td className="px-4 py-3">
                    <span className="font-medium text-fg">{p.papers.title ?? p.papers.url}</span>
                    {(p.papers.venue || p.papers.year) && (
                      <div className="mt-0.5 font-mono text-xs text-muted">
                        {[p.papers.venue, p.papers.year].filter(Boolean).join(" · ")}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted">{formatAuthors(p.papers.authors)}</td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted">
                    {formatDate(p.posted_at)}
                    {p.posted_by_label && <div>{p.posted_by_label}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={selected !== null} onClose={() => setSelected(null)}>
        {selected && <PaperDetail post={selected} teamId={teamId} userId={userId} />}
      </Modal>
    </div>
  );
}

function PaperDetail({
  post,
  teamId,
  userId,
}: {
  post: PaperPost;
  teamId: string;
  userId: string;
}) {
  const p = post.papers;
  const tags = [...new Set([...p.tags, ...p.keywords])];
  return (
    <div className="p-6">
      <h2 className="pr-8 text-base font-semibold">{p.title ?? p.url}</h2>
      {[p.venue, p.year, p.doi].some(Boolean) && (
        <div className="mt-1 font-mono text-xs text-muted">
          {[p.venue, p.year, p.doi].filter(Boolean).join(" · ")}
        </div>
      )}
      {p.authors.length > 0 && <div className="mt-2 text-sm text-muted">{p.authors.join(", ")}</div>}
      {p.abstract ? (
        <p className="mt-4 text-sm leading-relaxed">{p.abstract}</p>
      ) : (
        <p className="mt-4 text-sm italic text-muted">No abstract available.</p>
      )}
      {tags.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {tags.map((t) => (
            <span
              key={t}
              className="rounded-full border border-border px-2 py-0.5 font-mono text-xs text-muted"
            >
              {t}
            </span>
          ))}
        </div>
      )}
      <div className="mt-5 flex flex-wrap gap-4 text-sm">
        <a href={p.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
          Paper ↗
        </a>
        {p.code_url && (
          <a href={p.code_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
            Code ↗
          </a>
        )}
        {p.data_url && (
          <a href={p.data_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
            Data ↗
          </a>
        )}
      </div>
      <div className="mt-5 border-t border-border pt-3 font-mono text-xs text-muted">
        Posted {formatDate(post.posted_at)}
        {post.posted_by_label ? ` · ${post.posted_by_label}` : ""}
        {post.note && <div className="mt-1">“{post.note}”</div>}
      </div>

      <PaperEngagement paperId={p.id} teamId={teamId} userId={userId} />
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
