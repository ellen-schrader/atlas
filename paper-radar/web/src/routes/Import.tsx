import { type DragEvent, type ReactNode, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, FileUp, Info, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { bibtexImport, bibtexPreflight, type BibEntryPreview, type PreflightResult } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/**
 * Teach Atlas what your lab reads — by importing the library it already has.
 *
 * Replaces scraping URLs out of Teams PDF exports, which a user fairly called "quite
 * hacky": every reference manager exports BibTeX, and that metadata is already clean.
 *
 * The import is two steps on purpose. A 438-entry file is a big thing to do to a shared
 * lab, so Atlas shows exactly what it *would* do — new, duplicate, missing DOI,
 * unparseable — and writes nothing until you say so.
 */
export default function Import() {
  const { team } = useAppContext();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);

  const [fileName, setFileName] = useState<string | null>(null);
  const [bibtex, setBibtex] = useState<string | null>(null);
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [showProblems, setShowProblems] = useState(false);
  const [done, setDone] = useState<{ imported: number; skipped: number; failed: number } | null>(
    null,
  );

  async function accept(file: File) {
    setError(null);
    setDone(null);
    setPreflight(null);
    setFileName(file.name);
    setBusy(true);
    try {
      const text = await file.text();
      setBibtex(text);
      setPreflight(await bibtexPreflight(text, team.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBibtex(null);
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!bibtex) return;
    setBusy(true);
    setError(null);
    try {
      const result = await bibtexImport(bibtex, team.id);
      setDone(result);
      setPreflight(null);
      // The lab's corpus just changed underneath every cached view.
      await qc.invalidateQueries();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void accept(file);
  }

  const problems = (preflight?.entries ?? []).filter(
    (e) => e.status === "rejected" || e.status === "no_doi",
  );

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <header>
        <h1 className="text-display font-serif font-semibold tracking-tight text-fg">
          Teach Atlas what your lab reads
        </h1>
        <p className="mt-1.5 max-w-[62ch] text-sm text-muted">
          Import the library {team.name} already has. Atlas resolves the metadata, skips anything
          you’ve already posted, and shows you exactly what it will add — before it adds it.
        </p>
      </header>

      {done ? (
        <Done result={done} teamName={team.name} onBrowse={() => navigate("/papers")} />
      ) : (
        <>
          {/* drop zone */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              "flex flex-col items-center gap-2 rounded-card border-2 border-dashed px-6 py-12 text-center transition",
              dragging ? "border-accent bg-accent-weak" : "border-border-strong bg-surface",
            )}
          >
            <FileUp size={26} className="text-accent" />
            <p className="text-sm font-semibold text-fg">
              {fileName ?? "Drop your .bib file here"}
            </p>
            <p className="text-xs text-muted">or</p>
            <input
              ref={fileRef}
              type="file"
              accept=".bib,.bibtex,text/plain"
              className="sr-only"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void accept(f);
              }}
            />
            <Button variant="secondary" size="sm" onClick={() => fileRef.current?.click()}>
              Choose a file
            </Button>
          </div>

          {busy && !preflight && <p className="text-sm text-muted">Reading {fileName}…</p>}
          {error && (
            <p className="rounded-control border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}

          {preflight && (
            <section className="rounded-card border border-border bg-surface p-5">
              <h2 className="font-serif text-lg font-semibold tracking-tight">
                {fileName} — {preflight.entries.length} entries
              </h2>
              <p className="mb-4 mt-1 text-sm text-muted">Nothing has been imported yet.</p>

              <div className="flex flex-col gap-2">
                <Row kind="ok" n={preflight.new}>
                  new {preflight.new === 1 ? "paper" : "papers"}, metadata resolved
                </Row>
                <Row kind="muted" n={preflight.duplicates}>
                  already here, or listed twice — will be skipped
                </Row>
                <Row kind="warn" n={preflight.no_doi}>
                  missing a DOI — will be matched on their URL instead
                </Row>
                <Row kind="bad" n={preflight.rejected}>
                  unreadable — nothing to import from them
                </Row>
              </div>

              {problems.length > 0 && (
                <div className="mt-4">
                  <button
                    type="button"
                    onClick={() => setShowProblems((s) => !s)}
                    className="text-xs font-medium text-accent hover:underline"
                  >
                    {showProblems ? "Hide" : "Review"} the {problems.length}{" "}
                    {problems.length === 1 ? "problem" : "problems"} →
                  </button>
                  {showProblems && (
                    <ul className="mt-2.5 flex max-h-64 flex-col divide-y divide-border overflow-y-auto rounded-control border border-border">
                      {problems.map((e, i) => (
                        <Problem key={`${e.key}-${i}`} entry={e} />
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <div className="mt-5 flex flex-wrap gap-2">
                {/* `importable`, not `new`: papers without a DOI import too (matched on
                    URL), so promising `new` would under-count what actually lands. */}
                <Button onClick={commit} disabled={busy || preflight.importable === 0}>
                  {busy
                    ? "Importing…"
                    : preflight.importable === 0
                      ? "Nothing new to import"
                      : `Import ${preflight.importable} ${preflight.importable === 1 ? "paper" : "papers"}`}
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    setPreflight(null);
                    setBibtex(null);
                    setFileName(null);
                  }}
                >
                  Cancel
                </Button>
              </div>
            </section>
          )}

          <HowTo />
        </>
      )}
    </div>
  );
}

function Done({
  result,
  teamName,
  onBrowse,
}: {
  result: { imported: number; skipped: number; failed: number };
  teamName: string;
  onBrowse: () => void;
}) {
  return (
    <section className="rounded-card border border-accent/40 bg-accent-weak p-6">
      <h2 className="flex items-center gap-2 font-serif text-xl font-semibold tracking-tight">
        <Check size={20} className="text-accent" />
        {result.imported} {result.imported === 1 ? "paper" : "papers"} imported
      </h2>
      <p className="mt-1.5 text-sm text-muted">
        Atlas is already learning {teamName}’s taste from them. Embeddings compute in the
        background, so the map will fill in shortly.
        {result.skipped > 0 && ` ${result.skipped} were already here and were skipped.`}
        {result.failed > 0 && ` ${result.failed} couldn’t be read.`}
      </p>
      <Button className="mt-4" onClick={onBrowse}>
        Browse the papers
      </Button>
    </section>
  );
}

function Row({
  kind,
  n,
  children,
}: {
  kind: "ok" | "muted" | "warn" | "bad";
  n: number;
  children: ReactNode;
}) {
  if (n === 0) return null;
  const icon = {
    ok: <Check size={15} className="text-accent" />,
    muted: <Info size={15} className="text-faint" />,
    warn: <AlertTriangle size={15} className="text-warn" />,
    bad: <X size={15} className="text-danger" />,
  }[kind];

  return (
    <div className="flex items-baseline gap-2.5 text-sm">
      <span className="mt-0.5 shrink-0 self-start">{icon}</span>
      <span className="font-mono font-semibold tabular-nums text-fg">{n}</span>
      <span className="text-muted">{children}</span>
    </div>
  );
}

function Problem({ entry }: { entry: BibEntryPreview }) {
  return (
    <li className="flex flex-col gap-0.5 px-3 py-2 text-xs">
      <span className="truncate font-medium text-fg">
        {entry.title ?? <span className="font-mono text-faint">{entry.key || "(no key)"}</span>}
      </span>
      <span className={cn(entry.status === "rejected" ? "text-danger" : "text-warn")}>
        {entry.reason}
      </span>
    </li>
  );
}

/**
 * The export instructions live here, on the screen where you need them — not in a docs
 * site. "An explanation of how to get it" was the ask; this is the moment it's asked.
 */
function HowTo() {
  return (
    <section className="rounded-card border border-border bg-surface p-5">
      <h2 className="font-serif text-lg font-semibold tracking-tight">
        Where do I get a .bib file?
      </h2>
      <dl className="mt-3 flex flex-col gap-2.5 text-sm">
        <Step app="Zotero">
          Right-click your library or a collection → <b className="text-fg">Export Collection…</b> →
          format <b className="text-fg">BibTeX</b> → Save.
        </Step>
        <Step app="Mendeley">
          Select your references → <b className="text-fg">File → Export…</b> →{" "}
          <b className="text-fg">BibTeX (*.bib)</b>.
        </Step>
        <Step app="EndNote / Paperpile">
          Export with the <b className="text-fg">BibTeX</b> output style.
        </Step>
        <Step app="Google Scholar">
          Settings → show a <b className="text-fg">BibTeX</b> import link, then save entries one at a
          time.
        </Step>
      </dl>
      <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-faint">
        Papers keep the date <b className="text-muted">your lab shared them</b> — today, for an
        import — while their <b className="text-muted">publication date</b> is stored separately. Sort
        Papers by “Recently published” to read an imported back-catalogue in the order it came out.
      </p>
    </section>
  );
}

function Step({ app, children }: { app: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-3">
      <dt className="w-40 shrink-0 font-semibold text-fg">{app}</dt>
      <dd className="text-muted">{children}</dd>
    </div>
  );
}
