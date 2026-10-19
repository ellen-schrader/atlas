import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Globe, Loader2, Sparkles, Upload, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { useMyRole } from "@/hooks/useMyRole";
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
  "claude (your account)": "a lab member’s Claude (no cost to Atlas)",
  "claude-opus-5-5": "Claude Opus 5.5",
  "claude-opus-4-8": "Claude Opus 4.8",
};

/** One line on where the trial's data stands, for the collapsed panel's header. */
export function extractionSummary(facts: TrialFacts | null, documents: number): string {
  const docs = `${documents} ${documents === 1 ? "document" : "documents"}`;
  const status = facts?.extraction_status;
  if (status === "queued") return `${docs} · queued for the next batch`;
  if (status === "batched") return `${docs} · with Claude in a batch`;
  if (extractionRunning(status ?? null, facts?.extraction_started_at ?? null))
    return `${docs} · Claude is reading them`;
  if (status === "failed") return `${docs} · the last extraction failed`;
  if (facts?.extracted_at)
    return `${docs} · extracted by ${MODEL_NAMES[facts.extraction_model ?? ""] ?? facts.extraction_model} ${formatRelative(facts.extracted_at)}`;
  return documents ? `${docs} · not extracted yet` : "No documents yet";
}

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
  const [confirm, confirmDialog] = useConfirm();
  const { data: role } = useMyRole(team.id, userId);
  // The PDF just picked, waiting to be told what it is.
  const [file, setFile] = useState<File | null>(null);
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
    onSuccess: () => {
      setFile(null);
      refresh();
    },
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
  // The lab's spend is the owners' business (it's on their card): members
  // aren't asked to weigh it on every trial. Owners see it in Settings too.
  const owner = role === "owner";
  const budget = useQuery({
    queryKey: ["extraction-budget", team.id],
    queryFn: () => fetchExtractionBudget(team.id),
    staleTime: 60_000,
    enabled: owner,
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
  const queued = facts?.extraction_status === "queued";
  const batched = facts?.extraction_status === "batched";
  // Queued trials can still be extracted now (skipping the wait); a trial out
  // in a batch can't: that result is paid for and on its way.
  const busy = running || batched;
  // Numbered as the extraction read them ("Doc 2"); files added since are new.
  const readOrder = facts?.extraction_sources ?? [];
  const list = sources.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted">
        Claude reads these documents to get the trial’s design, results and who was enrolled. They
        stay private to {team.name}.
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
                // Wraps on a phone, where truncating left "PMC122…".
                className="min-w-0 flex-1 break-words text-left text-sm text-fg hover:text-accent sm:truncate"
              >
                {s.filename}
              </button>
              <span className="shrink-0 text-meta text-muted">
                {s.kind === "supplement" ? "Supplement" : "Paper"}
                <span className="hidden sm:inline"> · {(s.bytes / 1e6).toFixed(1)} MB</span>
              </span>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remove ${s.filename}`}
                disabled={remove.isPending || running}
                onClick={async () => {
                  if (
                    await confirm({
                      title: `Remove ${s.filename}?`,
                      body: "The data already extracted stays until the trial is extracted again.",
                      confirmLabel: "Remove",
                      danger: true,
                    })
                  )
                    remove.mutate(s);
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
        <Button
          variant="secondary"
          size="sm"
          disabled={upload.isPending || file !== null}
          onClick={() => fileRef.current?.click()}
        >
          <Upload size={14} aria-hidden />
          Upload PDF
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) setFile(f);
            e.target.value = "";
          }}
        />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={list.length === 0 || busy || extract.isPending}
            onClick={() => extract.mutate("now")}
          >
            Get data now
          </Button>
          <Button
            size="sm"
            disabled={list.length === 0 || busy || queued || extract.isPending}
            onClick={() => extract.mutate("batch")}
          >
            {busy || queued || extract.isPending ? (
              <Loader2 size={14} className="animate-spin" aria-hidden />
            ) : (
              <Sparkles size={14} aria-hidden />
            )}
            {queued ? "Queued" : facts?.extraction ? "Queue a fresh extraction" : "Queue extraction"}
          </Button>
        </div>
      </div>

      {file && (
        <form
          className="flex flex-wrap items-center gap-2 rounded-control border border-border p-3"
          onSubmit={(e) => {
            e.preventDefault();
            upload.mutate(file);
          }}
        >
          <label className="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-sm text-fg">
            <span className="min-w-0 truncate">
              What is <span className="font-medium">{file.name}</span>?
            </span>
            <select
              value={what}
              onChange={(e) => setWhat(e.target.value)}
              className="h-8 min-w-0 max-w-full truncate rounded-md border border-border bg-surface px-2 text-sm text-fg sm:max-w-80"
            >
              {papers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
              <option value="">Another paper</option>
              <option value="supplement">A supplement</option>
            </select>
          </label>
          <Button type="submit" size="sm" disabled={upload.isPending}>
            {upload.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />}
            Upload
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setFile(null)}>
            Cancel
          </Button>
        </form>
      )}

      {list.length > 0 && !busy && (
        <p className="text-meta text-muted">
          Queue: half price, ready within a few hours. Get data now: full price, about a minute.
        </p>
      )}

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
                    ? owner ? ` · about $${Number(facts.extraction_cost_usd).toFixed(2)}` : ""
                    : ""
                }. A fresh extraction replaces the values and their checks.`
              : list.length === 0
                ? "Not extracted yet. First fetch the open-access full text, or upload a PDF."
                : "Not extracted yet."}
      </p>
      {owner && budget.data && (
        <p className="text-meta text-faint">
          {team.name}’s extraction spend this month: ${budget.data.spent_usd.toFixed(2)} of $
          {budget.data.cap_usd.toFixed(0)} (only owners see this)
        </p>
      )}
      {confirmDialog}
    </div>
  );
}
