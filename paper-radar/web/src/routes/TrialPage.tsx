import { type ReactNode, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Check, ExternalLink, Loader2, Pencil, Plus, Undo2, X } from "lucide-react";

import { PaperPicker, type PickedPaper } from "@/components/PaperPicker";
import { usePaperModal } from "@/components/PaperModal";
import { useToast } from "@/components/Toast";
import { ExtractionView } from "@/components/trials/ExtractionView";
import { TrialSources } from "@/components/trials/TrialSources";
import { ChipGroup, RequireTrials, TherapyList, TrialsDisclaimer } from "@/components/trials/parts";
import { fetchSources } from "@/lib/extraction";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type FactsEdit,
  PATIENT_GROUPS,
  SETTINGS,
  THERAPY_CLASSES,
  THERAPY_COLOR,
  type TrialDetail,
  type TrialLink,
  classification,
  ctgovUrl,
  decideLink,
  fetchTrialDetail,
  linkPaper,
  phaseLabel,
  removeTrial,
  saveFacts,
  statusLabel,
  trialName,
} from "@/lib/trials";
import { useAppContext } from "@/routes/Layout";

export default function TrialPage() {
  return (
    <RequireTrials>
      <Trial />
    </RequireTrials>
  );
}

function Trial() {
  const { nct = "" } = useParams();
  const { team } = useAppContext();
  const { data, isLoading, error } = useQuery({
    queryKey: ["trial", team.id, nct],
    queryFn: () => fetchTrialDetail(team.id, nct),
    refetchInterval: (q) =>
      q.state.data &&
      (classification(q.state.data.facts, q.state.data.added_at) === "pending" ||
        q.state.data.facts?.extraction_status === "running")
        ? 5000
        : false,
  });

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6 sm:p-8">
      <Link
        to="/trials"
        className="inline-flex w-fit items-center gap-1.5 text-sm text-muted hover:text-fg"
      >
        <ArrowLeft size={14} aria-hidden /> All trials
      </Link>
      {isLoading && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Loader2 size={14} className="animate-spin" aria-hidden /> Loading…
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-danger">
          Couldn’t load this trial. Try again.
        </p>
      )}
      {data === null && (
        <p className="text-sm text-muted">
          {nct} isn’t on {team.name}’s list. <Link to="/trials" className="text-accent">Back to all trials</Link>
        </p>
      )}
      {data && <TrialBody d={data} />}
      <TrialsDisclaimer />
    </div>
  );
}

function TrialBody({ d }: { d: TrialDetail }) {
  const { team } = useAppContext();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const t = d.trial;
  const reg = t.registry ?? {};
  // The numbered documents the extraction's sources refer to (same order as
  // the extraction read them: papers, then supplements, oldest first).
  const sources = useQuery({
    queryKey: ["trial-sources", team.id, t.id],
    queryFn: () => fetchSources(team.id, t.id),
  });
  const name = trialName(t, d.facts);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["trial", team.id, t.nct_id] });
    qc.invalidateQueries({ queryKey: ["lab-trials", team.id] });
  };

  const remove = useMutation({
    mutationFn: () => removeTrial(team.id, t.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lab-trials", team.id] });
      toast({ message: `${name} removed. Atlas won’t add it back from papers.` });
      navigate("/trials");
    },
    onError: () => toast({ message: "Couldn’t remove the trial. Try again." }),
  });

  const design = reg.designModule?.designInfo;
  const facts = [
    phaseLabel(t.phases),
    design?.allocation && design.allocation.toLowerCase().replace(/_/g, "-"),
    design?.maskingInfo?.masking &&
      (design.maskingInfo.masking === "NONE"
        ? "open-label"
        : `${design.maskingInfo.masking.toLowerCase()} masking`),
    t.enrollment != null && `${t.enrollment.toLocaleString()} enrolled`,
  ].filter(Boolean);

  return (
    <>
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="text-display font-bold tracking-tight text-fg">{name}</h1>
          <Button
            variant="ghost"
            size="sm"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(`Take ${name} off ${team.name}’s list?`)) remove.mutate();
            }}
          >
            Remove from lab
          </Button>
        </div>
        <p className="max-w-[80ch] text-sm text-muted">{t.title}</p>
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-meta text-muted">
          <span>{facts.join(" · ")} ·</span>
          <a
            href={ctgovUrl(t.nct_id)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-accent hover:underline"
          >
            {t.nct_id} <ExternalLink size={12} aria-hidden />
          </a>
          <span>
            · {statusLabel(t.status)}
            {t.sponsor && ` · ${t.sponsor}`}
          </span>
        </div>
      </header>

      <Classification d={d} onSaved={refresh} />

      <Section title="Papers in Atlas">
        <Papers d={d} onChange={refresh} />
      </Section>

      <Section title="Data from the papers">
        <TrialSources trialId={t.id} facts={d.facts} onExtractionChange={refresh} />
      </Section>

      {d.facts?.extraction && (
        <ExtractionView
          trialId={t.id}
          extraction={d.facts.extraction}
          sources={(d.facts.extraction_sources ?? []).map(
            (id) => (sources.data ?? []).find((s) => s.id === id) ?? null,
          )}
          colours={{
            exp:
              THERAPY_COLOR[
                d.facts.therapy_classes.find((c) => c !== "chemotherapy") ?? "immunotherapy"
              ],
            ctrl: "var(--faint)",
          }}
        />
      )}

      <Section
        title="From ClinicalTrials.gov"
        aside={
          <span className="text-meta text-faint">
            Registry record{t.start_date && ` · started ${t.start_date}`}
          </span>
        }
      >
        <div className="flex flex-col gap-5">
          {(reg.armsInterventionsModule?.armGroups ?? []).length > 0 && (
            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold text-fg">Arms</h3>
              <ul className="grid gap-2 sm:grid-cols-2">
                {reg.armsInterventionsModule?.armGroups?.map((a) => (
                  <li key={a.label} className="rounded-control border border-border p-3">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="text-sm font-semibold text-fg">{a.label}</span>
                      {a.type && (
                        <span className="text-meta text-muted">
                          {a.type.toLowerCase().replace(/_/g, " ")}
                        </span>
                      )}
                    </div>
                    {a.description && (
                      <p className="mt-1 text-sm text-muted">{a.description}</p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <Outcomes title="Primary outcomes" items={reg.outcomesModule?.primaryOutcomes} />
          <Outcomes
            title="Secondary outcomes"
            items={reg.outcomesModule?.secondaryOutcomes}
            collapsed
          />
          {reg.eligibilityModule?.eligibilityCriteria && (
            <details className="group">
              <summary className="cursor-pointer text-sm font-semibold text-fg">
                Eligibility criteria
              </summary>
              <p className="mt-2 whitespace-pre-wrap text-sm text-muted">
                {reg.eligibilityModule.eligibilityCriteria}
              </p>
            </details>
          )}
        </div>
      </Section>
    </>
  );
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-card border border-border bg-surface p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-heading font-semibold text-fg">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Outcomes({
  title,
  items,
  collapsed = false,
}: {
  title: string;
  items?: { measure: string; timeFrame?: string }[];
  collapsed?: boolean;
}) {
  if (!items?.length) return null;
  const body = (
    <ul className="mt-2 flex flex-col gap-1.5">
      {items.map((o, i) => (
        <li key={i} className="text-sm text-fg">
          {o.measure}
          {o.timeFrame && <span className="text-muted"> · {o.timeFrame}</span>}
        </li>
      ))}
    </ul>
  );
  if (collapsed)
    return (
      <details>
        <summary className="cursor-pointer text-sm font-semibold text-fg">
          {title} ({items.length})
        </summary>
        {body}
      </details>
    );
  return (
    <div>
      <h3 className="text-sm font-semibold text-fg">{title}</h3>
      {body}
    </div>
  );
}

// --- classification ------------------------------------------------------------

function Classification({ d, onSaved }: { d: TrialDetail; onSaved: () => void }) {
  const { team, userId } = useAppContext();
  const f = d.facts;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<FactsEdit | null>(null);
  const save = useMutation({
    mutationFn: (edit: FactsEdit) => saveFacts(team.id, d.trial.id, userId, edit),
    onSuccess: () => {
      setEditing(false);
      onSaved();
    },
  });

  const start = () => {
    setDraft({
      acronym: f?.acronym ?? d.trial.acronym,
      settings: f?.settings ?? [],
      patient_groups: f?.patient_groups ?? [],
      therapy_classes: f?.therapy_classes ?? [],
    });
    save.reset();
    setEditing(true);
  };

  const source =
    f?.classified_by === "person"
      ? "Edited by a lab member"
      : f?.classified_by === "claude"
        ? "Suggested by Claude from the registry record"
        : classification(f, d.added_at) === "pending"
          ? "Claude is classifying this trial…"
          : "Not classified yet. Use Edit to set it.";

  if (editing && draft) {
    const toggle = <K extends "settings" | "patient_groups" | "therapy_classes">(
      key: K,
      value: FactsEdit[K][number],
    ) =>
      setDraft((cur) => {
        if (!cur) return cur;
        const list = cur[key] as string[];
        const next = list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
        return { ...cur, [key]: next };
      });
    return (
      <Section title="Classification">
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(draft);
          }}
        >
          <label className="flex max-w-xs flex-col gap-1 text-sm font-medium text-fg">
            Short name
            <Input
              value={draft.acronym ?? ""}
              maxLength={40}
              onChange={(e) => setDraft({ ...draft, acronym: e.target.value })}
              placeholder={d.trial.nct_id}
            />
          </label>
          <ChipGroup
            legend="Setting"
            options={SETTINGS}
            selected={draft.settings}
            onToggle={(v) => toggle("settings", v as never)}
          />
          <ChipGroup
            legend="Patient group"
            options={PATIENT_GROUPS}
            selected={draft.patient_groups}
            onToggle={(v) => toggle("patient_groups", v as never)}
          />
          <ChipGroup
            legend="Therapy (experimental arm)"
            options={THERAPY_CLASSES}
            selected={draft.therapy_classes}
            onToggle={(v) => toggle("therapy_classes", v as never)}
            swatches
          />
          {save.error && (
            <p role="alert" className="text-sm text-danger">
              Couldn’t save. Try again.
            </p>
          )}
          <div className="flex gap-2">
            <Button type="submit" disabled={save.isPending}>
              {save.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />} Save
            </Button>
            <Button type="button" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </form>
      </Section>
    );
  }

  return (
    <Section
      title="Classification"
      aside={
        <Button variant="ghost" size="sm" onClick={start}>
          <Pencil size={14} aria-hidden /> Edit
        </Button>
      }
    >
      <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
        <Fact label="Setting">
          {f?.settings.length ? f.settings.map((s) => SETTINGS[s]).join(", ") : "—"}
        </Fact>
        <Fact label="Patient group">
          {f?.patient_groups.length ? f.patient_groups.map((g) => PATIENT_GROUPS[g]).join(", ") : "—"}
        </Fact>
        <Fact label="Therapy">
          <TherapyList therapies={f?.therapy_classes ?? []} />
        </Fact>
      </dl>
      <p className="text-meta text-faint">{source}</p>
    </Section>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">{label}</dt>
      <dd className="mt-1 text-fg">{children}</dd>
    </div>
  );
}

// --- papers ------------------------------------------------------------------------

const PROVENANCE: Record<TrialLink["source"], string> = {
  nct_in_abstract: "NCT ID in abstract",
  acronym_in_title: "trial name in title",
  manual: "linked by a lab member",
};

function provenance(l: TrialLink): string {
  if (l.status === "auto") return `Linked automatically · ${PROVENANCE[l.source]}`;
  if (l.status === "suggested") return `Suggested · ${PROVENANCE[l.source]}, needs review`;
  if (l.status === "confirmed")
    return l.source === "manual" ? "Linked by a lab member" : "Confirmed by a lab member";
  return "Marked as not reporting this trial";
}

function Papers({ d, onChange }: { d: TrialDetail; onChange: () => void }) {
  const { team, userId } = useAppContext();
  const { openPaper } = usePaperModal();
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<PickedPaper | null>(null);
  const decide = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "confirmed" | "rejected" }) =>
      decideLink(id, userId, status),
    onSuccess: onChange,
  });
  const link = useMutation({
    mutationFn: (paperId: string) => {
      // A paper the lab once said "not this trial" to comes back by confirming.
      const old = d.links.find((l) => l.paper_id === paperId);
      return old ? decideLink(old.id, userId, "confirmed") : linkPaper(team.id, d.trial.id, paperId, userId);
    },
    onSuccess: () => {
      setPicked(null);
      setPicking(false);
      onChange();
    },
  });

  const linked = d.links.filter((l) => l.status === "auto" || l.status === "confirmed");
  const suggested = d.links.filter((l) => l.status === "suggested");
  const rejected = d.links.filter((l) => l.status === "rejected");

  const row = (l: TrialLink, actions: ReactNode) => (
    <li key={l.id} className="flex flex-wrap items-start gap-3 py-3">
      <div className="min-w-0 flex-1">
        <button
          type="button"
          onClick={() => openPaper(l.paper_id)}
          className="text-left text-sm font-medium text-fg hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {l.papers?.title ?? "Untitled paper"}
        </button>
        <div className="mt-0.5 text-meta text-muted">
          {[l.papers?.venue, l.papers?.year].filter(Boolean).join(" · ")}
          {(l.papers?.venue || l.papers?.year) && " · "}
          <span className={l.status === "suggested" ? "text-fg" : undefined}>{provenance(l)}</span>
        </div>
      </div>
      <div className="flex shrink-0 gap-1">{actions}</div>
    </li>
  );

  return (
    <div className="flex flex-col gap-2">
      {d.links.length === 0 && (
        <p className="text-sm text-muted">
          No lab papers linked yet. Papers that name {d.trial.nct_id} in their abstract are linked
          automatically.
        </p>
      )}
      {suggested.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-fg">To review · {suggested.length}</h3>
          <ul className="divide-y divide-border">
            {suggested.map((l) =>
              row(
                l,
                <>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ id: l.id, status: "confirmed" })}
                  >
                    <Check size={14} aria-hidden /> Reports this trial
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ id: l.id, status: "rejected" })}
                  >
                    <X size={14} aria-hidden /> No
                  </Button>
                </>,
              ),
            )}
          </ul>
        </div>
      )}
      {linked.length > 0 && (
        <ul className="divide-y divide-border">
          {linked.map((l) =>
            row(
              l,
              <Button
                size="sm"
                variant="ghost"
                disabled={decide.isPending}
                onClick={() => decide.mutate({ id: l.id, status: "rejected" })}
                aria-label={`Unlink ${l.papers?.title ?? "paper"}`}
              >
                Unlink
              </Button>,
            ),
          )}
        </ul>
      )}
      {rejected.length > 0 && (
        <details>
          <summary className="cursor-pointer text-meta text-muted">
            Not this trial · {rejected.length}
          </summary>
          <ul className="divide-y divide-border">
            {rejected.map((l) =>
              row(
                l,
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={decide.isPending}
                  onClick={() => decide.mutate({ id: l.id, status: "confirmed" })}
                >
                  <Undo2 size={14} aria-hidden /> Link again
                </Button>,
              ),
            )}
          </ul>
        </details>
      )}
      {decide.error && (
        <p role="alert" className="text-sm text-danger">
          Couldn’t save that. Try again.
        </p>
      )}

      {picking ? (
        <div className="flex flex-col gap-2 rounded-control border border-border p-3">
          <PaperPicker teamId={team.id} value={picked} onChange={setPicked} />
          {link.error && (
            <p role="alert" className="text-sm text-danger">
              Couldn’t link that paper. Try again.
            </p>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={!picked || link.isPending}
              onClick={() => picked && link.mutate(picked.id)}
            >
              Link paper
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPicking(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Button variant="ghost" size="sm" className="w-fit" onClick={() => setPicking(true)}>
          <Plus size={14} aria-hidden /> Link a paper
        </Button>
      )}
    </div>
  );
}
