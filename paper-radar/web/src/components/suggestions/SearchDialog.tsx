import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FlaskConical, Loader2 } from "lucide-react";

import { ChipGroup } from "@/components/trials/parts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { Textarea } from "@/components/ui/textarea";
import { createSearch, previewSearch, updateSearch } from "@/lib/api";
import {
  ARXIV_BIOLOGY,
  PAPER_SOURCE_LABEL,
  type SavedSearch,
  type SearchFields,
  SOURCES,
  type SourceKey,
  type SourceResult,
} from "@/lib/savedSearches";
import { cn, formatAuthors } from "@/lib/utils";

const SOURCE_OPTIONS = Object.fromEntries(SOURCES.map((s) => [s.key, s.label]));

const EMPTY: SearchFields = {
  name: "",
  query: "",
  sources: ["pubmed", "biorxiv", "arxiv"],
  arxiv_categories: ARXIV_BIOLOGY,
};

/** New search, or edit one (`search`). A new one can start from `initial`
 *  (a suggested search). Saving runs it at once, so the first week's
 *  suggestions arrive within a minute rather than next week. */
export function SearchDialog({
  open,
  onClose,
  teamId,
  search,
  initial,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  teamId: string;
  search?: SavedSearch | null;
  initial?: Partial<SearchFields>;
  onSaved?: (s: SavedSearch, rerun: boolean) => void;
}) {
  const title = search ? "Edit search" : "New search";
  return (
    <Modal
      open={open}
      onClose={onClose}
      label={title}
      className="max-w-[720px]"
    >
      <div className="flex flex-col gap-4 overflow-y-auto p-6 pt-14">
        <div>
          <h2 className="text-heading font-semibold text-fg">{title}</h2>
          <p className="mt-1 text-sm text-muted">
            Atlas runs it every week and lists the new papers on this page.
          </p>
        </div>
        {open && (
          <SearchForm
            key={search?.id ?? `new:${initial?.query ?? ""}`}
            teamId={teamId}
            search={search ?? null}
            initial={initial}
            onDone={(s, rerun) => {
              onSaved?.(s, rerun);
              onClose();
            }}
            onCancel={onClose}
          />
        )}
      </div>
    </Modal>
  );
}

function SearchForm({
  teamId,
  search,
  initial,
  onDone,
  onCancel,
}: {
  teamId: string;
  search: SavedSearch | null;
  initial?: Partial<SearchFields>;
  onDone: (s: SavedSearch, rerun: boolean) => void;
  onCancel: () => void;
}) {
  const qc = useQueryClient();
  const [f, setF] = useState<SearchFields>(
    search
      ? {
          name: search.name,
          query: search.query,
          sources: search.sources,
          arxiv_categories: search.arxiv_categories,
        }
      : { ...EMPTY, ...initial },
  );
  // The preview answers the form as it was when tested; it shows only while
  // the form still says the same.
  const [tested, setTested] = useState<{
    asked: string;
    results: SourceResult[];
  } | null>(null);

  const preview = useMutation({
    // The arguments travel with the request, so the answer is filed under
    // what was asked even if the form changed while it ran.
    mutationFn: (asked: SearchFields) =>
      previewSearch(teamId, asked.query, asked.sources, asked.arxiv_categories),
    onSuccess: (results, asked) =>
      setTested({ asked: previewKey(asked), results }),
  });
  const save = useMutation({
    mutationFn: () => {
      // The name is optional: without one, the search is called by its query.
      const named = { ...f, name: f.name.trim() || nameFor(f.query) };
      return search
        ? updateSearch(teamId, search.id, named)
        : createSearch(teamId, named);
    },
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ["saved-searches", teamId] });
      const rerun =
        !search ||
        search.query !== s.query ||
        search.sources.join() !== s.sources.join() ||
        search.arxiv_categories.join() !== s.arxiv_categories.join();
      onDone(s, rerun);
    },
  });

  const current = tested !== null && tested.asked === previewKey(f);
  // A new search may go unnamed (it is called by its query); an existing one
  // keeps a name rather than being renamed by clearing the field.
  const ready =
    f.query.trim() && f.sources.length > 0 && (!search || f.name.trim());
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (ready && !save.isPending) save.mutate();
  };
  const toggle = (v: string) =>
    setF((cur) => ({
      ...cur,
      sources: cur.sources.includes(v as SourceKey)
        ? cur.sources.filter((x) => x !== v)
        : [...cur.sources, v as SourceKey],
    }));

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <label className="flex flex-col gap-1 text-sm font-medium text-fg">
        What to look for
        <Textarea
          required
          maxLength={2000}
          rows={3}
          spellCheck={false}
          className="font-mono text-[13px]"
          value={f.query}
          onChange={(e) => {
            setF({ ...f, query: e.target.value });
          }}
          placeholder="tertiary lymphoid structures AND breast cancer"
        />
        <span className="text-xs font-normal text-muted">
          A few keywords work, or paste a search from PubMed as it is.
        </span>
      </label>
      <details className="-mt-2 text-xs text-muted">
        <summary className="cursor-pointer select-none font-medium hover:text-fg">
          Tips for a sharper search
        </summary>
        <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-4">
          <li>
            Put phrases in quotes: <code>"flow matching"</code> finds the
            phrase, not the two words anywhere.
          </li>
          <li>
            Combine with AND, OR, NOT and brackets:{" "}
            <code>"flow matching" AND (protein OR molecule)</code>.
          </li>
          <li>
            A trailing * matches word endings: <code>organoid*</code>.
          </li>
          <li>
            PubMed tags such as [tiab] (title or abstract) and [au] (author)
            work on every source; filters like [pt] apply on PubMed only.
          </li>
        </ul>
      </details>
      <ChipGroup
        legend="Where to look"
        options={SOURCE_OPTIONS}
        selected={f.sources}
        onToggle={toggle}
      />
      {f.sources.includes("arxiv") && (
        <ArxivSubjects
          value={f.arxiv_categories}
          onChange={(v) => setF((cur) => ({ ...cur, arxiv_categories: v }))}
        />
      )}

      <label className="flex flex-col gap-1 text-sm font-medium text-fg">
        <span>
          Name{" "}
          {!search && (
            <span className="font-normal text-muted">(optional)</span>
          )}
        </span>
        <Input
          required={!!search}
          maxLength={120}
          value={f.name}
          onChange={(e) => setF({ ...f, name: e.target.value })}
          placeholder={
            f.query.trim() ? nameFor(f.query) : "TLS in breast cancer"
          }
        />
      </label>

      <div className="flex flex-col gap-3 rounded-card border border-border bg-surface-2 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted">
            Check what it finds before you save it.
          </p>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={
              !f.query.trim() || f.sources.length === 0 || preview.isPending
            }
            onClick={() => preview.mutate(f)}
          >
            {preview.isPending ? (
              <Loader2 size={13} className="animate-spin" aria-hidden />
            ) : (
              <FlaskConical size={13} aria-hidden />
            )}
            Preview last week
          </Button>
        </div>
        {preview.isPending && (
          <p className="text-sm text-muted" role="status">
            Searching… arXiv asks for a few seconds between requests.
          </p>
        )}
        {preview.error && !preview.isPending && (
          <p role="alert" className="text-sm text-danger">
            {preview.error.message}
          </p>
        )}
        {tested && current && !preview.isPending && (
          <PreviewResults results={tested.results} />
        )}
      </div>

      {save.error && (
        <p role="alert" className="text-sm text-danger">
          {save.error.message}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={!ready || save.isPending}>
          {save.isPending && (
            <Loader2 size={14} className="animate-spin" aria-hidden />
          )}
          {search ? "Save changes" : "Save and run"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** What a preview depends on, as one string to compare. */
function previewKey(f: SearchFields): string {
  return JSON.stringify([f.query, f.sources, f.arxiv_categories]);
}

type SubjectMode = "biology" | "all" | "custom";

/** Which arXiv subjects to keep to: most of arXiv is physics, maths and
 *  computer science, so new searches keep to quantitative biology. */
function ArxivSubjects({
  value,
  onChange,
}: {
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [mode, setMode] = useState<SubjectMode>(
    value.length === 0
      ? "all"
      : value.join() === ARXIV_BIOLOGY.join()
        ? "biology"
        : "custom",
  );
  const [custom, setCustom] = useState(
    mode === "custom" ? value.join(" ") : "",
  );
  const codes = (text: string) => text.split(/[\s,]+/).filter(Boolean);
  const pick = (m: SubjectMode) => {
    setMode(m);
    onChange(
      m === "biology" ? ARXIV_BIOLOGY : m === "all" ? [] : codes(custom),
    );
  };
  const options: { key: SubjectMode; label: string }[] = [
    { key: "biology", label: "Biology" },
    { key: "all", label: "All of arXiv" },
    { key: "custom", label: "Choose subjects" },
  ];
  return (
    <fieldset className="-mt-2 flex flex-col gap-1.5">
      <legend className="mb-1.5 text-xs font-medium text-muted">
        On arXiv, look in
      </legend>
      <div role="radiogroup" className="flex flex-wrap gap-1.5">
        {options.map((o) => (
          <button
            key={o.key}
            type="button"
            role="radio"
            aria-checked={mode === o.key}
            onClick={() => pick(o.key)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
              mode === o.key
                ? "border-accent/50 bg-accent-weak text-fg"
                : "border-border text-muted hover:text-fg",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
      {mode === "biology" && (
        <p className="text-xs text-muted">
          Quantitative biology, including machine-learning papers cross-listed
          there.
        </p>
      )}
      {mode === "custom" && (
        <label className="flex flex-col gap-1 text-xs text-muted">
          <Input
            value={custom}
            spellCheck={false}
            className="font-mono text-[13px]"
            placeholder="q-bio.GN cs.LG"
            aria-label="arXiv subject codes"
            onChange={(e) => {
              setCustom(e.target.value);
              onChange(codes(e.target.value));
            }}
          />
          <span>
            Subject codes, separated by spaces (
            <a
              href="https://arxiv.org/category_taxonomy"
              target="_blank"
              rel="noreferrer"
              className="underline hover:text-fg"
            >
              list of codes
            </a>
            ). Left empty, all of arXiv.
          </span>
        </label>
      )}
    </fieldset>
  );
}

function PreviewResults({ results }: { results: SourceResult[] }) {
  return (
    <ul className="flex flex-col gap-3">
      {results.map((r) => (
        <li key={r.source} className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-fg">
            {SOURCE_OPTIONS[r.source]}{" "}
            <span className="font-normal text-muted">
              {r.error
                ? ""
                : r.count === 0
                  ? "· nothing this week"
                  : `· ${r.count} this week`}
            </span>
          </p>
          {r.error && (
            <p className="flex items-start gap-1.5 text-xs text-danger">
              <AlertTriangle size={13} className="mt-px shrink-0" aria-hidden />
              {r.error}
            </p>
          )}
          {r.papers.length > 0 && (
            <ul className="flex flex-col gap-1 border-l-2 border-border pl-3">
              {r.papers.slice(0, 5).map((p) => (
                <li key={p.url} className="text-xs">
                  <a
                    href={p.url}
                    target="_blank"
                    rel="noreferrer"
                    className={cn(
                      "text-fg hover:text-accent hover:underline",
                      p.in_lab && "text-muted",
                    )}
                  >
                    {p.title}
                  </a>
                  <span className="text-faint">
                    {" "}
                    · {formatAuthors(p.authors, 1)} ·{" "}
                    {PAPER_SOURCE_LABEL[p.source] ?? p.source}
                    {p.in_lab && " · already in the library"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}

/** A name for a search that wasn't given one: its query, cut short. */
function nameFor(query: string): string {
  const q = query.trim().replace(/\s+/g, " ");
  // By characters, not UTF-16 units, so an emoji isn't cut in half.
  const chars = Array.from(q);
  return chars.length > 60 ? `${chars.slice(0, 59).join("")}…` : q;
}
