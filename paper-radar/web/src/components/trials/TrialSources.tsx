import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Globe, Loader2, Sparkles, Upload, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { ApiError, fetchOpenAccess, startExtraction } from "@/lib/api";
import {
  type TrialSource,
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
  onExtractionChange,
}: {
  trialId: string;
  facts: TrialFacts | null;
  onExtractionChange: () => void;
}) {
  const { team, userId } = useAppContext();
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<"paper" | "supplement">("paper");
  const key = ["trial-sources", team.id, trialId];
  const sources = useQuery({ queryKey: key, queryFn: () => fetchSources(team.id, trialId) });
  const refresh = () => qc.invalidateQueries({ queryKey: key });

  const upload = useMutation({
    mutationFn: (file: File) => uploadSource(team.id, trialId, userId, file, kind),
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
    mutationFn: () => startExtraction(team.id, trialId),
    onSuccess: onExtractionChange,
    onError: (e) =>
      toast({ message: e instanceof ApiError ? e.message : "Couldn’t start the extraction." }),
  });

  const open = async (s: TrialSource) => {
    try {
      window.open(await sourceUrl(s), "_blank", "noopener");
    } catch {
      toast({ message: "Couldn’t open that file." });
    }
  };

  const running = facts?.extraction_status === "running";
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
          {list.map((s, i) => (
            <li key={s.id} className="flex items-center gap-3 px-3 py-2">
              <span className="w-6 shrink-0 font-mono text-meta text-faint">{i + 1}</span>
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
        <label className="flex items-center gap-1.5 text-sm text-muted">
          <span className="sr-only">Kind of file</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as "paper" | "supplement")}
            className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
          >
            <option value="paper">Paper</option>
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
        <div className="ml-auto">
          <Button
            size="sm"
            disabled={list.length === 0 || running || extract.isPending}
            onClick={() => extract.mutate()}
          >
            {running || extract.isPending ? (
              <Loader2 size={14} className="animate-spin" aria-hidden />
            ) : (
              <Sparkles size={14} aria-hidden />
            )}
            {facts?.extraction ? "Extract again" : "Start extraction"}
          </Button>
        </div>
      </div>

      <p className="text-meta text-faint" aria-live="polite">
        {running
          ? `Claude is reading ${list.length} ${list.length === 1 ? "document" : "documents"}… (started ${formatRelative(facts?.extraction_started_at ?? null)}; usually 1–3 minutes)`
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
    </div>
  );
}
