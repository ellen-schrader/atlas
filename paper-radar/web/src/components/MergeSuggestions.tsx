import { useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Copy, GitMerge } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import {
  type MergeSuggestion,
  type SuggestedPaper,
  useDecideMergeSuggestion,
  useMergeSuggestions,
} from "@/hooks/useMergeSuggestions";
import { cn, formatAuthors } from "@/lib/utils";

/** "Same paper?" on a paper that is one half of an open suggestion. */
export function SamePaperBanner({ paperId, teamId }: { paperId: string; teamId: string }) {
  const { data: suggestions } = useMergeSuggestions(teamId);
  const [comparing, setComparing] = useState<MergeSuggestion | null>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const [, setSearchParams] = useSearchParams();

  // Merging from the preprint's own page deletes the paper on screen: show the
  // one it became, on the page or in the modal, whichever this is.
  function merged(s: MergeSuggestion) {
    if (s.preprint.id !== paperId) return;
    if (location.pathname === `/papers/${paperId}`) {
      navigate(`/papers/${s.published.id}`, { replace: true });
      return;
    }
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("paper", s.published.id);
        return next;
      },
      { replace: true },
    );
  }

  const mine = (suggestions ?? []).filter(
    (s) => s.preprint.id === paperId || s.published.id === paperId,
  );
  if (mine.length === 0) return null;

  return (
    <>
      {mine.map((s) => {
        const isPreprint = s.preprint.id === paperId;
        const other = isPreprint ? s.published : s.preprint;
        return (
          <div
            key={s.id}
            className="mt-4 flex flex-col gap-2 rounded-control border border-accent/40 bg-accent-weak px-3 py-2.5 text-xs leading-relaxed text-accent sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="flex items-start gap-2">
              <Copy size={14} className="mt-px shrink-0" aria-hidden />
              <span>
                {isPreprint
                  ? "This looks like the preprint of "
                  : `This looks like the published version of a preprint${s.preprint.venue ? ` on ${s.preprint.venue}` : ""} in your lab, `}
                <strong className="font-semibold">“{other.title ?? other.url}”</strong>
                {isPreprint && source(other) ? ` (${source(other)})` : ""}. Same paper?
              </span>
            </span>
            <Button size="sm" variant="secondary" className="shrink-0" onClick={() => setComparing(s)}>
              Compare
            </Button>
          </div>
        );
      })}
      <CompareDialog
        suggestion={comparing}
        teamId={teamId}
        onClose={() => setComparing(null)}
        onMerged={merged}
      />
    </>
  );
}

/** "Possible duplicates (n)" on the Library page: every open suggestion. */
export function MergeSuggestionsButton({ teamId }: { teamId: string }) {
  const { data: suggestions } = useMergeSuggestions(teamId);
  const [listing, setListing] = useState(false);
  const [comparing, setComparing] = useState<MergeSuggestion | null>(null);
  const n = suggestions?.length ?? 0;
  if (n === 0) return null;

  return (
    <>
      <Button variant="secondary" onClick={() => setListing(true)} className="shrink-0">
        <Copy size={15} /> Possible duplicates ({n})
      </Button>
      <Modal open={listing && !comparing} onClose={() => setListing(false)} label="Possible duplicates">
        <div className="border-b border-border px-6 py-5 pl-14">
          <h2 className="font-serif text-lg font-semibold tracking-tight text-fg">Possible duplicates</h2>
          <p className="mt-1 text-sm text-muted">
            Preprints that look like a published paper your lab also holds. Atlas can’t be sure, so
            it asks: compare each pair and merge it, or mark it as not the same.
          </p>
        </div>
        <ul className="flex flex-col divide-y divide-border px-6 py-2">
          {(suggestions ?? []).map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-4 py-3">
              <div className="min-w-0 text-sm">
                <div className="truncate font-medium text-fg">{s.published.title ?? s.published.url}</div>
                <div className="truncate text-xs text-muted">
                  {source(s.preprint) || "Preprint"} → {source(s.published) || "published"}
                </div>
              </div>
              <Button size="sm" variant="secondary" className="shrink-0" onClick={() => setComparing(s)}>
                Compare
              </Button>
            </li>
          ))}
        </ul>
      </Modal>
      <CompareDialog
        suggestion={comparing}
        teamId={teamId}
        onClose={() => {
          setComparing(null);
          if (n <= 1) setListing(false);
        }}
      />
    </>
  );
}

/** The two papers side by side, and the decision. */
function CompareDialog({
  suggestion,
  teamId,
  onClose,
  onMerged,
}: {
  suggestion: MergeSuggestion | null;
  teamId: string;
  onClose: () => void;
  onMerged?: (s: MergeSuggestion) => void;
}) {
  const decide = useDecideMergeSuggestion(teamId);
  const [busy, setBusy] = useState<"merge" | "dismiss" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function answer(merge: boolean) {
    if (!suggestion) return;
    setBusy(merge ? "merge" : "dismiss");
    setError(null);
    try {
      await decide(suggestion.id, merge);
      onClose();
      if (merge) onMerged?.(suggestion);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Modal open={suggestion !== null} onClose={busy ? () => {} : onClose} label="Same paper?" className="max-w-[760px]">
      {suggestion && (
        <>
          <div className="border-b border-border px-6 py-5 pl-14">
            <h2 className="font-serif text-lg font-semibold tracking-tight text-fg">Same paper?</h2>
            <p className="mt-1 text-sm text-muted">
              The titles match {Math.round(suggestion.score * 100)}% and they share an author.
            </p>
          </div>
          <div className="grid gap-4 px-6 py-5 sm:grid-cols-2">
            <PaperColumn label="Preprint" paper={suggestion.preprint} />
            <PaperColumn label="Published version" paper={suggestion.published} highlight />
          </div>
          <div className="px-6 pb-2 text-xs leading-relaxed text-muted">
            Merging keeps the published version. Comments, reactions, reading status and lab tags
            move to it, and the preprint stays linked from it. It changes the paper for every lab
            that holds either version, and can’t be undone.
          </div>
          {error && <p className="px-6 pt-2 text-sm text-danger">{error}</p>}
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border bg-surface-2 px-6 py-4">
            <Button variant="ghost" onClick={onClose} disabled={busy !== null}>
              Cancel
            </Button>
            <Button variant="secondary" onClick={() => void answer(false)} disabled={busy !== null}>
              {busy === "dismiss" ? "Saving…" : "Not the same"}
            </Button>
            <Button onClick={() => void answer(true)} disabled={busy !== null}>
              <GitMerge size={15} /> {busy === "merge" ? "Merging…" : "Merge"}
            </Button>
          </div>
        </>
      )}
    </Modal>
  );
}

function PaperColumn({
  label,
  paper,
  highlight = false,
}: {
  label: string;
  paper: SuggestedPaper;
  highlight?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1.5 rounded-card border p-4",
        highlight ? "border-accent/50 bg-accent-weak/40" : "border-border",
      )}
    >
      <span className="text-eyebrow font-semibold uppercase tracking-eyebrow text-muted">{label}</span>
      <span className="text-sm font-semibold text-fg">{paper.title ?? paper.url}</span>
      {paper.authors.length > 0 && <span className="text-xs text-muted">{formatAuthors(paper.authors)}</span>}
      {source(paper) && <span className="text-xs font-medium text-fg">{source(paper)}</span>}
      {paper.doi && <span className="break-all font-mono text-[11px] text-muted">DOI {paper.doi}</span>}
    </div>
  );
}

function source(p: SuggestedPaper): string {
  return [p.venue, p.year].filter(Boolean).join(" · ");
}
