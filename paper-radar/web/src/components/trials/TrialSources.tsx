import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Globe, Loader2, Sparkles, Upload, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { ApiError, fetchExtractionBudget, fetchOpenAccess, startExtraction } from "@/lib/api";
import {
  type TrialSource,
  extractionRunning,
  fetchSources,
  removeSource,
  sourceUrl,
  uploadSource,
} from "@/lib/extraction";
import type { TrialFacts } from "@/lib/trials";
import { formatRelative } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

const MODEL_NAMES: Record<string, string> = {
  "claude-opus-5-5": "Claude Opus 5.5",
  "claude-opus-4-8": "Claude Opus 4.8",
};

/** The files behind a trial's data, and the button that has Claude read them. */
export function TrialSources({
  trialId,
  facts,
  papers,
  onExtractionChange,
}: {
  trialId: string;
  facts: TrialFacts | null;
  /** The lab papers linked to the trial: an uploaded PDF can say which it is. */
  papers: { id: string; title: string }[];
  onExtractionChange: () => void;
}) {
  const { team, userId } = useAppContext();
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  // "supplement", or the paper the PDF is ("" for a paper not in the list).
  const [what, setWhat] = useState<string>(papers[0]?.id ?? "");
  const key = ["trial-sources", team.id, trialId];
  const sources = useQuery({ queryKey: key, queryFn: () => fetchSources(team.id, trialId) });
  const refresh = () => qc.invalidateQueries({ queryKey: key });

  const upload = useMutation({
    mutationFn: (file: File) =>
      uploadSource(
        team.id,
        trialId,
        userId,
        file,
        what === "supplement" ? "supplement" : "paper",
        what && what !== "supplement" ? what : null,
      ),
    onSuccess: refresh,
    onError: (e) => toast({ message: e instanceof Error ? e.message : "Upload failed." }),
  });
  const remove = useMutation({
    mutationFn: (s: TrialSource) => removeSource(s),
    onSuccess: refresh,
    onError: () => toast({ message: "Couldn’t remove that file. Try again." }),
  });
  const openAccess = useMutation({
    mutationFn: () => fetchOpenAccess(team.id, trialId),
    onSuccess: (r) => {
      refresh();
      const parts = [
        r.fetched.length && `Fetched ${r.fetched.length} open-access full ${r.fetched.length === 1 ? "text" : "texts"}.`,
        r.closed.length &&
          `${r.closed.length} linked ${r.closed.length === 1 ? "paper isn’t" : "papers aren’t"} open access: upload ${r.closed.length === 1 ? "its" : "their"} PDF.`,
        !r.fetched.length && !r.closed.length && !r.have.length && "No linked papers to fetch. Link the trial’s papers first.",
        !r.fetched.length && !r.closed.length && r.have.length > 0 && "Every linked paper already has its full text here.",
      ].filter(Boolean);
      toast({ message: parts.join(" ") });
    },
    onError: (e) =>
      toast({ message: e instanceof ApiError ? e.message : "Couldn’t reach Europe PMC." }),
  });
  const extract = useMutation({
    mutationFn: (mode: "batch" | "now") => startExtraction(team.id, trialId, mode),
    onSuccess: () => {
      onExtractionChange();
      qc.invalidateQueries({ queryKey: ["extraction-budget", team.id] });
    },
    onError: (e) =>
      toast({ message: e instanceof ApiError ? e.message : "Couldn’t start the extraction." }),
  });
  const budget = useQuery({
    queryKey: ["extraction-budget", team.id],
    queryFn: () => fetchExtractionBudget(team.id),
    staleTime: 60_000,
  });

  const open = async (s: TrialSource) => {
    try {
      window.open(await sourceUrl(s), "_blank", "noopener");
    } catch {
      toast({ message: "Couldn’t open that file." });
    }
  };

  const running = extractionRunning(
    facts?.extraction_status ?? null,
    facts?.extraction_started_at ?? null,
  );
  const stalled = facts?.extraction_status === "running" && !running;
  const waiting = facts?.extraction_status === "queued" || facts?.extraction_status === "batched";
  const busy = running || waiting;
  // Numbered as the extraction read them ("Doc 2"); files added since are new.
  const readOrder = facts?.extraction_sources ?? [];
  const list = sources.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        Claude reads these to extract the trial’s design, results and who was enrolled. Fetch the
        open-access full text of linked papers, or upload PDFs (papers and supplements). Files stay
        private to {team.name}.
      </p>

      {list.length > 0 && (
        <ul className="divide-y divide-border rounded-control border border-border">
          {list.map((s) => (
            <li key={s.id} className="flex items-center gap-3 px-3 py-2">
              <span
                className="w-12 shrink-0 font-mono text-meta text-faint"
                title={readOrder.includes(s.id) ? "Its number in the extraction" : "Added since the last extraction"}
              >
                {readOrder.includes(s.id) ? `Doc ${readOrder.indexOf(s.id) + 1}` : "new"}
              </span>
              {s.origin === "europepmc" ? (
                <Globe size={15} aria-hidden className="shrink-0 text-muted" />
              ) : (
                <FileText size={15} aria-hidden className="shrink-0 text-muted" />
              )}
              <button
                type="button"
                onClick={() => open(s)}
                className="min-w-0 flex-1 truncate text-left text-sm text-fg hover:text-accent"
              >
                {s.filename}
              </button>
              <span className="shrink-0 text-meta text-muted">
                {s.kind === "supplement" ? "Supplement" : "Paper"} · {(s.bytes / 1e6).toFixed(1)} MB
              </span>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remove ${s.filename}`}
                disabled={remove.isPending || running}
                onClick={() => {
                  if (window.confirm(`Remove ${s.filename}?`)) remove.mutate(s);
                }}
              >
                <X size={14} aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={openAccess.isPending}
          onClick={() => openAccess.mutate()}
        >
          {openAccess.isPending ? (
            <Loader2 size={14} className="animate-spin" aria-hidden />
          ) : (
            <Globe size={14} aria-hidden />
          )}
          Fetch open access
        </Button>
        <label className="flex min-w-0 items-center gap-1.5 text-sm text-muted">
          <span className="sr-only">What the PDF is</span>
          <select
            value={what}
            onChange={(e) => setWhat(e.target.value)}
            className="h-8 max-w-64 truncate rounded-md border border-border bg-surface px-2 text-sm text-fg"
          >
            {papers.map((p) => (
              <option key={p.id} value={p.id}>
                Paper: {p.title}
              </option>
            ))}
            <option value="">Another paper</option>
            <option value="supplement">Supplement</option>
          </select>
        </label>
        <Button
          variant="secondary"
          size="sm"
          disabled={upload.isPending}
          onClick={() => fileRef.current?.click()}
        >
          {upload.isPending ? (
            <Loader2 size={14} className="animate-spin" aria-hidden />
          ) : (
            <Upload size={14} aria-hidden />
          )}
          Upload PDF
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload.mutate(f);
            e.target.value = "";
          }}
        />
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={list.length === 0 || busy || extract.isPending}
            onClick={() => extract.mutate("now")}
            title="Full price, about a minute"
          >
            Extract now
          </Button>
          <Button
            size="sm"
            disabled={list.length === 0 || busy || extract.isPending}
            onClick={() => extract.mutate("batch")}
            title="Half price; results usually within a few hours"
          >
            {busy || extract.isPending ? (
              <Loader2 size={14} className="animate-spin" aria-hidden />
            ) : (
              <Sparkles size={14} aria-hidden />
            )}
            {facts?.extraction ? "Queue re-extraction" : "Queue extraction"}
          </Button>
        </div>
      </div>

      <p className="text-meta text-faint" aria-live="polite">
        {facts?.extraction_status === "queued"
          ? facts.extraction_error
            ? `Queued · ${facts.extraction_error}`
            : `Queued for the next batch (half price): results usually within a few hours.`
          : facts?.extraction_status === "batched"
            ? `With Claude in a batch: results usually within the hour of it being sent.`
            : running
          ? `Claude is reading ${list.length} ${list.length === 1 ? "document" : "documents"}… (started ${formatRelative(facts?.extraction_started_at ?? null)}; usually 1–3 minutes)`
          : stalled
            ? "The last extraction stopped without finishing. Start it again."
            : facts?.extraction_status === "failed"
            ? `Extraction failed: ${facts.extraction_error ?? "unknown error"}`
            : facts?.extracted_at
              ? `Extracted by ${MODEL_NAMES[facts.extraction_model ?? ""] ?? facts.extraction_model} ${formatRelative(facts.extracted_at)}${
                  facts.extraction_cost_usd != null
                    ? ` · about $${Number(facts.extraction_cost_usd).toFixed(2)}`
                    : ""
                }. Extracting again replaces the values and their checks.`
              : "Not extracted yet."}
      </p>
      {budget.data && (
        <p className="text-meta text-faint">
          {team.name}’s extraction spend this month: ${budget.data.spent_usd.toFixed(2)} of $
          {budget.data.cap_usd.toFixed(0)}
        </p>
      )}
    </div>
  );
}
