import { type FormEvent, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { usePaperModal } from "@/components/PaperModal";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { usePapers } from "@/hooks/usePapers";
import { postPaper, semanticSearch } from "@/lib/api";
import type { PaperPost, SemanticHit } from "@/lib/types";
import { cn, formatAuthors, formatDate } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

export default function Papers() {
  const { team } = useAppContext();
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-lg font-semibold">Papers</h1>
        <p className="text-sm text-muted">Post a paper and browse your lab’s collection.</p>
      </div>
      <PostPaperCard teamId={team.id} />
      <PaperList teamId={team.id} />
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

type SearchMode = "text" | "semantic";

function PaperList({ teamId }: { teamId: string }) {
  const { data, isLoading, error } = usePapers(teamId);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("text");
  const [hits, setHits] = useState<SemanticHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  if (isLoading) return <p className="text-sm text-muted">Loading papers…</p>;
  if (error) return <p className="text-sm text-danger">Couldn’t load papers.</p>;

  const posts = data ?? [];
  if (posts.length === 0) {
    return <p className="text-sm text-muted">No papers yet — post one above.</p>;
  }

  async function runSemantic(e: FormEvent) {
    e.preventDefault();
    if (mode !== "semantic") return; // Enter in text mode filters live already
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setSearchError(null);
    try {
      setHits(await semanticSearch(q, teamId));
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  }

  const filtered = posts.filter((p) => paperMatches(p, query.trim()));
  const rows: { post: PaperPost; similarity?: number }[] =
    mode === "semantic"
      ? (hits ?? []).map((h) => ({ post: h.post, similarity: h.similarity }))
      : filtered.map((post) => ({ post }));

  return (
    <div className="flex flex-col gap-3">
      <form onSubmit={runSemantic} className="flex items-center gap-3">
        <div className="flex shrink-0 rounded-md border border-border p-0.5 text-xs">
          {(["text", "semantic"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={cn(
                "rounded px-2 py-1 capitalize transition",
                mode === m ? "bg-surface-2 font-medium text-fg" : "text-muted hover:text-fg",
              )}
            >
              {m}
            </button>
          ))}
        </div>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={
            mode === "text"
              ? "Search title, author, abstract, tag…"
              : "Describe a topic, then press Enter…"
          }
          className="max-w-xs"
        />
        {mode === "semantic" && (
          <Button type="submit" size="sm" disabled={searching || !query.trim()}>
            {searching ? "…" : "Search"}
          </Button>
        )}
        <span className="text-xs text-muted">
          {mode === "text"
            ? `${filtered.length} of ${posts.length}`
            : hits !== null
              ? `${hits.length} matches`
              : ""}
        </span>
      </form>
      {searchError && mode === "semantic" && (
        <p className="text-xs text-danger">{searchError}</p>
      )}

      {mode === "semantic" && hits === null ? (
        <p className="text-sm text-muted">
          Semantic search ranks the lab’s papers by meaning, not keywords — describe a topic above.
        </p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted">No papers match “{query}”.</p>
      ) : (
        <PaperTable rows={rows} />
      )}
    </div>
  );
}

function PaperTable({ rows }: { rows: { post: PaperPost; similarity?: number }[] }) {
  const { openPaper } = usePaperModal();
  const showSimilarity = rows.some((r) => r.similarity !== undefined);
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
            {showSimilarity && <th className="px-4 py-2.5 font-medium">Match</th>}
            <th className="px-4 py-2.5 font-medium">Title</th>
            <th className="px-4 py-2.5 font-medium">Authors</th>
            <th className="px-4 py-2.5 font-medium">Posted</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ post: p, similarity }) => (
            <tr
              key={p.id}
              onClick={() => openPaper(p.papers.id)}
              className="cursor-pointer border-b border-border align-top last:border-0 hover:bg-surface-2"
            >
              {showSimilarity && (
                <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted">
                  {similarity !== undefined ? `${Math.round(similarity * 100)}%` : ""}
                </td>
              )}
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
  );
}
