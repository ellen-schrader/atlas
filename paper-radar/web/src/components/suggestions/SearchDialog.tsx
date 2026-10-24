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
};

/** New search, or edit one (`search`). Saving runs it at once, so the first
 *  week's suggestions arrive within a minute rather than next week. */
export function SearchDialog({
  open,
  onClose,
  teamId,
  search,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  teamId: string;
  search?: SavedSearch | null;
  onSaved?: (s: SavedSearch, rerun: boolean) => void;
}) {
  const title = search ? "Edit search" : "New saved search";
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
            Runs once a week on what’s new. What it finds is suggested to you
            alone; the papers you import go to the lab’s library.
          </p>
        </div>
        {open && (
          <SearchForm
            key={search?.id ?? "new"}
            teamId={teamId}
            search={search ?? null}
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
  onDone,
  onCancel,
}: {
  teamId: string;
  search: SavedSearch | null;
  onDone: (s: SavedSearch, rerun: boolean) => void;
  onCancel: () => void;
}) {
  const qc = useQueryClient();
  const [f, setF] = useState<SearchFields>(
    search
      ? { name: search.name, query: search.query, sources: search.sources }
      : EMPTY,
  );
  // The preview answers the query as it was when tested; editing it again
  // makes that answer stale, so it goes.
  const [tested, setTested] = useState<{
    query: string;
    results: SourceResult[];
  } | null>(null);

  const preview = useMutation({
    mutationFn: () => previewSearch(teamId, f.query, f.sources),
    onSuccess: (results) => setTested({ query: f.query, results }),
  });
  const save = useMutation({
    mutationFn: () =>
      search ? updateSearch(teamId, search.id, f) : createSearch(teamId, f),
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ["saved-searches", teamId] });
      const rerun =
        !search ||
        search.query !== s.query ||
        search.sources.join() !== s.sources.join();
      onDone(s, rerun);
    },
  });

  const ready = f.name.trim() && f.query.trim() && f.sources.length > 0;
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
        Name
        <Input
          required
          maxLength={120}
          value={f.name}
          onChange={(e) => setF({ ...f, name: e.target.value })}
          placeholder="Tertiary lymphoid structures"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm font-medium text-fg">
        Query
        <Textarea
          required
          maxLength={2000}
          rows={3}
          spellCheck={false}
          className="font-mono text-[13px]"
          value={f.query}
          onChange={(e) => {
            setF({ ...f, query: e.target.value });
            if (tested && tested.query !== e.target.value) setTested(null);
          }}
          placeholder={
            '("tertiary lymphoid structure*"[tiab] OR TLS[tiab]) AND cancer'
          }
        />
        <span className="text-xs font-normal text-muted">
          Paste your PubMed search as it is, or type keywords. AND, OR, NOT,
          brackets, “quoted phrases”, a trailing * and tags such as [tiab] or
          [au] work everywhere; PubMed-only filters like [pt] apply on PubMed
          alone.
        </span>
      </label>
      <ChipGroup
        legend="Search in"
        options={SOURCE_OPTIONS}
        selected={f.sources}
        onToggle={toggle}
      />

      <div className="flex flex-col gap-3 rounded-card border border-border bg-surface-2 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted">
            See what it would have found in the past week.
          </p>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={
              !f.query.trim() || f.sources.length === 0 || preview.isPending
            }
            onClick={() => preview.mutate()}
          >
            {preview.isPending ? (
              <Loader2 size={13} className="animate-spin" aria-hidden />
            ) : (
              <FlaskConical size={13} aria-hidden />
            )}
            Test query
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
        {tested && !preview.isPending && (
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
