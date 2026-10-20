import { type ReactNode, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleDashed, ClipboardCheck, ExternalLink, FileText, Pencil, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { SourcePanel } from "@/components/trials/SourcePanel";
import { Button } from "@/components/ui/button";
import {
  CONTEXT_LABELS,
  DIMENSION_LABELS,
  type Dimension,
  type Endpoint,
  type Extraction,
  type Phase,
  ROLE_LABELS,
  type Source,
  type TrialSource,
  countEdits,
  editFact,
  fetchReviews,
  mediansText,
  openSourceFile,
  setVerified,
  treatmentName,
} from "@/lib/extraction";
import { headline, reviewGroups } from "@/lib/compare";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/** Colours of the two arms: the trial's leading therapy class, and the
 *  neutral data channel for control. */
export interface ArmColours {
  exp: string;
  ctrl: string;
}

interface Ctx {
  trialId: string;
  /** The documents as Claude numbered them; null where a file has since been removed. */
  sources: (TrialSource | null)[];
  reviews: Set<string>;
  colours: ArmColours;
  onChange: () => void;
  /** In review mode numbers can be corrected and groups marked verified;
   *  outside it the page is for reading. */
  reviewing: boolean;
  /** The group being reviewed. */
  current: string | null;
  /** Shows where a value came from: the cited part of a full text in the
   *  source panel, a PDF at its page in a new tab. */
  showSource: (source: Source) => void;
}

/** Each review group's source, for "Show source" in the review bar. */
function groupSource(x: Extraction, path: string): Source | null {
  if (path === "design") return x.design.source;
  if (path === "schedule") return x.arms.find((a) => a.role === "experimental")?.source ?? null;
  if (path === "adverse_events") return x.adverse_events[0]?.source ?? null;
  if (path === "enrolment") return x.enrolment.source;
  if (path === "context") return x.context.find((c) => c.source)?.source ?? null;
  const i = Number(path.split(".")[1]);
  return x.endpoints[i]?.source ?? null;
}

function groupTitle(x: Extraction, path: string): string {
  const fixed: Record<string, string> = {
    design: "Question and design",
    schedule: "Treatment",
    adverse_events: "Adverse events",
    enrolment: "Who was enrolled",
    context: "Details that affect comparison",
  };
  return fixed[path] ?? x.endpoints[Number(path.split(".")[1])]?.name ?? path;
}

const groupId = (path: string) => `review-${path.replace(/\./g, "-")}`;

/** "p = 0.0044 (1-sided)", "p < 0.001": the extraction keeps the paper's text. */
function pText(v: string): string {
  const t = v.trim();
  if (/^p\b/i.test(t)) return t;
  return /^[<>≤≥=]/.test(t) ? `p ${t}` : `p = ${t}`;
}

/** Everything Claude extracted, grouped as on the mock-up's trial view. Each
 *  group names its source and can be marked verified; numbers can be corrected
 *  (logged, and the correction clears "verified"). */
export function ExtractionView({
  trialId,
  extraction: x,
  extractedAt,
  sources,
  colours,
}: {
  trialId: string;
  extraction: Extraction;
  /** Keys the checks and corrections to this extraction: a new one refetches. */
  extractedAt: string | null;
  sources: (TrialSource | null)[];
  colours: ArmColours;
}) {
  const { team } = useAppContext();
  const qc = useQueryClient();
  const reviews = useQuery({
    queryKey: ["trial-reviews", team.id, trialId, extractedAt],
    queryFn: () => fetchReviews(team.id, trialId),
  });
  const edits = useQuery({
    queryKey: ["trial-edits", team.id, trialId, extractedAt],
    queryFn: () => countEdits(team.id, trialId, extractedAt),
  });
  const onChange = () => {
    qc.invalidateQueries({ queryKey: ["trial-reviews", team.id, trialId] });
    qc.invalidateQueries({ queryKey: ["trial-edits", team.id, trialId] });
    qc.invalidateQueries({ queryKey: ["trial", team.id] });
  };
  const groups = reviewGroups(x);
  const done = reviews.data ? groups.filter((g) => reviews.data.has(g)).length : null;
  const [chosen, setCurrent] = useState<string | null>(null);
  // A group a fresh extraction no longer has (fewer endpoints) ends the review.
  const current = chosen && groups.includes(chosen) ? chosen : null;
  // The source in the panel, if it's open.
  const [shown, setShown] = useState<Source | null>(null);
  // A new extraction is a new set of values: start its review from scratch.
  useEffect(() => {
    setCurrent(null);
    setShown(null);
  }, [extractedAt]);
  // While reviewing with the panel open, it follows the group being checked.
  useEffect(() => {
    if (current) setShown((s) => (s ? (groupSource(x, current) ?? s) : s));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);
  const toast = useToast();
  const showSource = async (source: Source) => {
    const doc = sources[source.doc - 1];
    if (doc?.media_type !== "application/pdf") return setShown(source);
    try {
      await openSourceFile(doc, source.page);
    } catch {
      toast({ message: "Couldn’t open the source." });
    }
  };
  const reviewing = current !== null;
  const ctx: Ctx = {
    trialId,
    sources,
    reviews: reviews.data ?? new Set(),
    colours,
    onChange,
    reviewing,
    current,
    showSource,
  };
  const exp = x.arms.find((a) => a.role === "experimental");
  const ctrl = x.arms.find((a) => a.role === "control");
  const firstUnchecked = () => groups.find((g) => !reviews.data?.has(g)) ?? groups[0];
  const lead = headline(x);

  return (
    <div className="flex flex-col gap-6">
      <section
        aria-label="Key results"
        className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-card border border-border bg-surface p-5"
      >
        <div className="min-w-0 flex-1">
          <div className="text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
            Key results
          </div>
          <div className="mt-1 font-mono text-card font-semibold text-fg">{lead || "No headline result extracted"}</div>
          <p className="mt-1 text-meta text-muted">
            {done == null
              ? "Extracted by Claude"
              : done === groups.length
                ? `All ${groups.length} groups checked against their sources`
                : `${done} of ${groups.length} groups checked against their sources`}
            {!!edits.data &&
              ` · ${edits.data} ${edits.data === 1 ? "value" : "values"} corrected by the lab (every change is logged)`}
          </p>
        </div>
        {!reviewing && (
          <Button variant={done === groups.length ? "secondary" : "default"} onClick={() => setCurrent(firstUnchecked())}>
            <ClipboardCheck size={16} aria-hidden />
            {done === groups.length ? "Review again" : done ? "Continue review" : "Review the data"}
          </Button>
        )}
      </section>

      <Group title="Question" path="design" source={x.design.source} ctx={ctx}>
        <dl className="grid gap-3 sm:grid-cols-2">
          {(
            [
              ["P", "Population", x.pico.population],
              ["I", "Intervention", x.pico.intervention],
              ["C", "Comparator", x.pico.comparator],
              ["O", "Outcome", x.pico.outcome],
            ] as const
          ).map(([k, label, v]) => (
            <div key={k} className="flex gap-3">
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-control bg-surface-2 font-mono text-sm font-semibold text-fg">
                {k}
              </span>
              <div>
                <dt className="text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
                  {label}
                </dt>
                <dd className="text-sm text-fg">{v}</dd>
              </div>
            </div>
          ))}
        </dl>
        <p className="mt-3 font-mono text-meta text-muted">
          {[
            x.design.phase,
            x.design.randomisation_ratio && `randomised ${x.design.randomisation_ratio}`,
            x.design.blinding,
            x.design.analysis_population,
            x.design.data_cutoff && `data cut-off ${x.design.data_cutoff}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </Group>

      {x.schedule.length > 0 && (
        <Group title="Treatment" path="schedule" source={exp?.source ?? null} ctx={ctx}>
          <Schedule
            phases={x.schedule}
            colours={colours}
            expLabel={exp?.label ?? "Experimental"}
            ctrlLabel={ctrl?.label ?? "Control"}
            expN={exp?.n_randomised ?? null}
            ctrlN={ctrl?.n_randomised ?? null}
          />
        </Group>
      )}

      {x.endpoints.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          {x.endpoints.map((e, i) => (
            <EndpointPanel key={i} e={e} path={`endpoints.${i}`} ctx={ctx} />
          ))}
        </div>
      )}

      {x.adverse_events.length > 0 && (
        <Group
          title="Adverse events"
          path="adverse_events"
          source={x.adverse_events[0]?.source ?? null}
          ctx={ctx}
        >
          <AdverseEvents x={x} ctx={ctx} />
        </Group>
      )}

      <Enrolment x={x} ctx={ctx} />

      {x.context.length > 0 && (
        <Group title="Details that affect comparison" path="context" source={null} ctx={ctx}>
          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {x.context.map((c, i) => (
              <div key={i}>
                <dt className="text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
                  {CONTEXT_LABELS[c.key] ?? c.key}
                </dt>
                <dd className="text-sm text-fg">
                  {c.value}{" "}
                  {c.source && <SourceLink source={c.source} ctx={ctx} />}
                </dd>
              </div>
            ))}
          </dl>
        </Group>
      )}

      {x.caveats && (
        <details className="rounded-card border border-border bg-surface p-4">
          <summary className="cursor-pointer text-sm font-semibold text-fg">
            Claude’s notes on this extraction
          </summary>
          <p className="mt-2 whitespace-pre-wrap text-sm text-muted">{x.caveats}</p>
        </details>
      )}

      {shown && (
        <SourcePanel
          trialId={trialId}
          source={shown}
          doc={sources[shown.doc - 1] ?? null}
          onClose={() => setShown(null)}
        />
      )}

      {current && (
        <ReviewBar
          x={x}
          groups={groups}
          current={current}
          ctx={ctx}
          onMove={setCurrent}
          onDone={() => setCurrent(null)}
        />
      )}
    </div>
  );
}

/** Review mode's bar: one group at a time, its source a click away, and
 *  "verified" moves on to the next one not yet checked. */
function ReviewBar({
  x,
  groups,
  current,
  ctx,
  onMove,
  onDone,
}: {
  x: Extraction;
  groups: string[];
  current: string;
  ctx: Ctx;
  onMove: (path: string) => void;
  onDone: () => void;
}) {
  const { team, userId } = useAppContext();
  const toast = useToast();
  const i = groups.indexOf(current);
  const source = groupSource(x, current);
  const doc = source ? ctx.sources[source.doc - 1] : null;
  const verified = ctx.reviews.has(current);
  useEffect(() => {
    document.getElementById(groupId(current))?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [current]);
  // The next group not yet checked, after this one; else the next one.
  const next = () => {
    const after = [...groups.slice(i + 1), ...groups.slice(0, i)];
    return after.find((g) => !ctx.reviews.has(g) && g !== current) ?? null;
  };
  const verify = useMutation({
    mutationFn: () => setVerified(team.id, ctx.trialId, userId, current, true),
    onSuccess: () => {
      ctx.onChange();
      const n = next();
      if (n) onMove(n);
      else {
        toast({ message: "Every group is checked." });
        onDone();
      }
    },
    onError: () => toast({ message: "Couldn’t save that. Try again." }),
  });
  const label = source
    ? [`Doc ${source.doc}`, source.where, source.page && `p. ${source.page}`].filter(Boolean).join(" · ")
    : "No source given: check it against the papers";

  return (
    <div
      role="region"
      aria-label="Review"
      className="sticky bottom-4 z-20 flex flex-col gap-3 rounded-card border border-border-strong bg-surface p-4 shadow-lg sm:flex-row sm:items-center"
    >
      <div className="min-w-0 flex-1">
        <div className="text-meta text-muted">
          Checking {i + 1} of {groups.length}
          {verified && " · already verified"}
        </div>
        <div className="font-semibold text-fg">{groupTitle(x, current)}</div>
        <div className="truncate text-meta text-muted" title={label}>
          {label}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {doc && source && (
          <Button variant="secondary" size="sm" onClick={() => ctx.showSource(source)}>
            {doc.media_type === "application/pdf" ? (
              <ExternalLink size={14} aria-hidden />
            ) : (
              <FileText size={14} aria-hidden />
            )}
            Show source
          </Button>
        )}
        <Button size="sm" disabled={verify.isPending || verified} onClick={() => verify.mutate()}>
          <Check size={14} aria-hidden /> Matches the source
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onMove(groups[(i + 1) % groups.length])}
        >
          Skip
        </Button>
        <Button variant="ghost" size="sm" onClick={onDone}>
          Done
        </Button>
      </div>
      <p className="text-meta text-faint sm:hidden">Tap a number to correct it.</p>
    </div>
  );
}

// --- building blocks -------------------------------------------------------------

function SourceLink({ source, ctx }: { source: Source; ctx: Ctx }) {
  const doc = ctx.sources[source.doc - 1];
  const label = [`Doc ${source.doc}`, source.where, source.page && `p. ${source.page}`]
    .filter(Boolean)
    .join(" · ");
  if (!doc)
    return (
      <span className="inline-block max-w-[min(22rem,100%)] truncate text-meta text-faint" title={label}>
        {label}
      </span>
    );
  return (
    <button
      type="button"
      title={
        doc.media_type === "application/pdf"
          ? `${label} · open ${doc.filename}${source.page ? ` at page ${source.page}` : ""}`
          : `${label} · show it beside the values`
      }
      onClick={() => ctx.showSource(source)}
      className="inline-flex max-w-[min(22rem,100%)] items-center gap-1 text-meta text-muted hover:text-accent"
    >
      <FileText size={12} aria-hidden className="shrink-0" />
      <span className="truncate">{label}</span>
    </button>
  );
}

function VerifyToggle({ path, ctx }: { path: string; ctx: Ctx }) {
  const { team, userId } = useAppContext();
  const on = ctx.reviews.has(path);
  const toggle = useMutation({
    mutationFn: () => setVerified(team.id, ctx.trialId, userId, path, !on),
    onSuccess: ctx.onChange,
  });
  // Reading, not reviewing: only a check worth knowing about is shown.
  if (!ctx.reviewing)
    return on ? (
      <span className="inline-flex items-center gap-1 text-meta text-accent">
        <Check size={12} aria-hidden /> Verified
      </span>
    ) : null;
  return (
    <button
      type="button"
      aria-pressed={on}
      disabled={toggle.isPending}
      onClick={() => toggle.mutate()}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-meta transition",
        on
          ? "border-accent/50 bg-accent-weak text-accent"
          : "border-dashed border-border-strong text-muted hover:text-fg",
      )}
    >
      {on ? <Check size={12} aria-hidden /> : <CircleDashed size={12} aria-hidden />}
      {on ? "Verified" : "Not yet verified"}
    </button>
  );
}

function Group({
  title,
  path,
  source,
  ctx,
  aside,
  children,
}: {
  title: string;
  path: string;
  source: Source | null;
  ctx: Ctx;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      id={groupId(path)}
      className={cn(
        "flex scroll-mt-6 flex-col gap-3 rounded-card border bg-surface p-5 transition",
        ctx.current === path ? "border-accent ring-2 ring-accent/30" : "border-border",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-heading font-semibold text-fg">{title}</h3>
        <div className="flex flex-wrap items-center gap-2">
          {aside}
          {source && <SourceLink source={source} ctx={ctx} />}
          <VerifyToggle path={path} ctx={ctx} />
        </div>
      </div>
      {children}
    </section>
  );
}

/** A number the lab can correct in place. */
function EditableNumber({
  value,
  path,
  ctx,
  suffix = "",
  className,
}: {
  value: number | null;
  path: string;
  ctx: Ctx;
  suffix?: string;
  className?: string;
}) {
  const { team } = useAppContext();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const save = useMutation({
    mutationFn: (v: number | null) => editFact(team.id, ctx.trialId, path, v),
    onSuccess: () => {
      setEditing(false);
      ctx.onChange();
    },
    onError: () => toast({ message: "Couldn’t save the correction." }),
  });
  if (!ctx.reviewing)
    return (
      <span className={cn("font-mono", className)}>
        {value == null ? <span className="text-faint" title="Not reported">n/r</span> : `${value}${suffix}`}
      </span>
    );
  if (editing)
    return (
      <form
        className="inline-flex items-center gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          const t = draft.trim();
          const n = t === "" ? null : Number(t);
          if (n !== null && Number.isNaN(n)) return;
          save.mutate(n);
        }}
      >
        <input
          autoFocus
          inputMode="decimal"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Escape") return;
            // Handled: cancelling the edit mustn't also close the source panel.
            e.preventDefault();
            setEditing(false);
          }}
          aria-label="Corrected value (empty for not reported)"
          className="h-7 w-20 rounded-md border border-border bg-surface px-1.5 font-mono text-sm text-fg"
        />
        <Button type="submit" size="sm" disabled={save.isPending}>
          Save
        </Button>
      </form>
    );
  return (
    <button
      type="button"
      title="Correct this value"
      onClick={() => {
        setDraft(value == null ? "" : String(value));
        setEditing(true);
      }}
      className={cn(
        "group inline-flex items-center gap-1 rounded font-mono hover:bg-surface-2",
        className,
      )}
    >
      {value == null ? <span className="text-faint" title="Not reported">n/r</span> : `${value}${suffix}`}
      <Pencil size={11} aria-hidden className="text-faint group-hover:text-accent" />
    </button>
  );
}

function Bars({
  caption,
  exp,
  ctrl,
  colours,
  expPath,
  ctrlPath,
  ctx,
}: {
  caption?: string;
  exp: number | null;
  ctrl: number | null;
  colours: ArmColours;
  expPath: string;
  ctrlPath: string;
  ctx: Ctx;
}) {
  const bar = (v: number | null, colour: string, path: string, label: string) => (
    <div className="flex items-center gap-2">
      <span className="w-20 shrink-0 text-meta text-muted">{label}</span>
      <div className="h-3 flex-1 overflow-hidden rounded-[4px] bg-surface-2">
        {v != null && (
          <div className="h-full rounded-[4px]" style={{ width: `${Math.min(100, v)}%`, background: colour }} />
        )}
      </div>
      <EditableNumber value={v} path={path} ctx={ctx} suffix="%" className="w-16 justify-end text-sm" />
    </div>
  );
  return (
    <div className="flex flex-col gap-1">
      {caption && <div className="text-sm text-fg">{caption}</div>}
      {bar(exp, colours.exp, expPath, "Experimental")}
      {bar(ctrl, colours.ctrl, ctrlPath, "Control")}
    </div>
  );
}

function EndpointPanel({ e, path, ctx }: { e: Endpoint; path: string; ctx: Ctx }) {
  const primary = e.role === "primary" || e.role === "co_primary";
  const ci = (lo: number | null, hi: number | null) =>
    lo != null && hi != null ? ` (95% CI ${lo} to ${hi})` : "";
  return (
    <Group
      title={e.name}
      path={path}
      source={e.source}
      ctx={ctx}
      aside={
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[11px] font-semibold",
            primary ? "bg-accent text-accent-fg" : "border border-border-strong text-muted",
          )}
        >
          {ROLE_LABELS[e.role]}
        </span>
      }
    >
      {(e.exp_value != null || e.ctrl_value != null) && (
        <Bars
          caption={e.timepoint ?? undefined}
          exp={e.exp_value}
          ctrl={e.ctrl_value}
          colours={ctx.colours}
          expPath={`${path}.exp_value`}
          ctrlPath={`${path}.ctrl_value`}
          ctx={ctx}
        />
      )}
      <p className="text-sm text-fg">
        {e.kind === "rate" ? (
          e.difference == null && !ctx.reviewing ? (
            <span className="text-muted">
              Difference not reported
              {e.exp_value != null &&
                e.ctrl_value != null &&
                ` (the rates are ${Math.round((e.exp_value - e.ctrl_value) * 10) / 10} pp apart)`}
            </span>
          ) : (
            <>
              Difference <EditableNumber value={e.difference} path={`${path}.difference`} ctx={ctx} suffix=" pp" />
              {ci(e.difference_ci_low, e.difference_ci_high)}
            </>
          )
        ) : (
          <>
            HR <EditableNumber value={e.hr} path={`${path}.hr`} ctx={ctx} />
            {ci(e.hr_ci_low, e.hr_ci_high)}
          </>
        )}
        {e.p_value && <span className="text-muted"> · {pText(e.p_value)}</span>}
      </p>
      {mediansText(e) && <p className="font-mono text-sm text-fg">{mediansText(e)}</p>}
      <p className="text-meta text-muted">
        {[
          e.definition,
          e.events != null && `${e.events} events`,
          e.median_followup_months != null && `median follow-up ${e.median_followup_months} mo`,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
    </Group>
  );
}

/** Adverse events as a table: eight pairs of 0–100% bars hid 5-point
 *  differences and took half the page. */
function AdverseEvents({ x, ctx }: { x: Extraction; ctx: Ctx }) {
  const dot = (colour: string) => (
    <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: colour }} />
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] text-sm">
        <thead className="text-left text-meta text-muted">
          <tr className="border-b border-border">
            <th className="py-2 pr-3 font-normal">Event</th>
            <th className="px-2 py-2 text-right font-normal">
              <span className="inline-flex items-center gap-1.5">{dot(ctx.colours.exp)} Experimental</span>
            </th>
            <th className="px-2 py-2 text-right font-normal">
              <span className="inline-flex items-center gap-1.5">{dot(ctx.colours.ctrl)} Control</span>
            </th>
            <th className="py-2 pl-2 text-right font-normal">Difference</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {x.adverse_events.map((a, i) => {
            const d = a.exp_pct != null && a.ctrl_pct != null ? Math.round((a.exp_pct - a.ctrl_pct) * 10) / 10 : null;
            return (
              <tr key={i}>
                <td className="py-2 pr-3 text-fg">{a.label}</td>
                <td className="px-2 py-2 text-right">
                  <EditableNumber value={a.exp_pct} path={`adverse_events.${i}.exp_pct`} ctx={ctx} suffix="%" />
                </td>
                <td className="px-2 py-2 text-right">
                  <EditableNumber value={a.ctrl_pct} path={`adverse_events.${i}.ctrl_pct`} ctx={ctx} suffix="%" />
                </td>
                <td className="py-2 pl-2 text-right font-mono text-muted">
                  {d == null ? "—" : `${d > 0 ? "+" : ""}${d} pp`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// --- treatment schedule ---------------------------------------------------------------

const BLOCK: Record<Phase["kind"], string> = {
  chemotherapy: "bg-[var(--ch-off)] text-fg",
  surgery: "border border-border-strong text-muted",
  radiotherapy: "bg-surface-3 text-fg",
  immunotherapy: "bg-surface-3 text-fg",
  adc: "bg-surface-3 text-fg",
  targeted: "bg-surface-3 text-fg",
  endocrine: "bg-surface-3 text-fg",
  observation: "border border-dashed border-border-strong text-muted",
  other: "bg-surface-3 text-fg",
};

function Schedule({
  phases,
  colours,
  expLabel,
  ctrlLabel,
  expN,
  ctrlN,
}: {
  phases: Phase[];
  colours: ArmColours;
  expLabel: string;
  ctrlLabel: string;
  expN: number | null;
  ctrlN: number | null;
}) {
  // Surgery is a fixed block, wide enough to say what it is; other blocks
  // scale with their weeks.
  const flex = (p: Phase) => (p.kind === "surgery" ? "0 0 58px" : `${p.weeks ?? 8} 1 0`);
  // The phase whose full doses are open below the chart. The blocks carry
  // short names only; the exact regimen is a click (or tap) away, never only
  // on hover.
  const [open, setOpen] = useState<number | null>(null);
  const shown = open != null && phases[open] ? open : null;
  const full = (p: Phase, a: string | null) => (a ? `${p.label} + ${a}` : p.label);
  const row = (arm: "exp" | "ctrl") => {
    const add = (p: Phase) => (arm === "exp" ? p.experimental_add : p.control_add);
    return (
      <div className="flex gap-1">
        {phases.map((p, i) => {
          const a = add(p);
          const first = a && (i === 0 || add(phases[i - 1]) !== a);
          const placebo = a && /placebo/i.test(a);
          return (
            <button
              key={i}
              type="button"
              aria-pressed={shown === i}
              aria-label={`${p.kind === "surgery" ? "Surgery" : p.label}: show doses`}
              onClick={() => setOpen(shown === i ? null : i)}
              // The highlight is a ring inside the phase block (below), not an
              // outline around the column: the chart's scroller clipped that,
              // and neighbours' outlines ran into each other across the gap.
              className="group flex min-w-0 cursor-pointer flex-col gap-1 text-left focus-visible:outline-none"
              style={{ flex: flex(p) }}
              title={full(p, a)}
            >
              <div
                className={cn(
                  "flex h-4 items-center overflow-hidden whitespace-nowrap rounded-[3px] px-1.5 text-[10px] font-semibold",
                  !a && "opacity-0",
                  placebo && "border border-dashed border-border-strong font-medium text-muted",
                )}
                style={a && !placebo ? { background: arm === "exp" ? colours.exp : colours.ctrl, color: "var(--bg)" } : undefined}
              >
                {first ? treatmentName(a) : ""}
              </div>
              <div
                className={cn(
                  "flex h-8 items-center justify-center overflow-hidden whitespace-nowrap rounded-[4px] px-1 text-[11px] transition",
                  BLOCK[p.kind],
                  shown === i
                    ? "ring-2 ring-inset ring-accent"
                    : "group-hover:ring-1 group-hover:ring-inset group-hover:ring-fg/40",
                  "group-focus-visible:ring-2 group-focus-visible:ring-inset group-focus-visible:ring-accent",
                )}
              >
                {/* Its own span, so a long name ends in "…" instead of losing both ends. */}
                <span className="min-w-0 truncate">{p.kind === "surgery" ? "Surgery" : treatmentName(p.label)}</span>
              </div>
            </button>
          );
        })}
      </div>
    );
  };
  const n = (v: number | null) => (v != null ? ` · n ${v}` : "");
  return (
    <div className="flex flex-col gap-3">
      {/* Only the chart scrolls sideways on a phone; the doses below wrap. */}
      <div className="overflow-x-auto">
        <div className="min-w-[560px]">
        <div className="mb-1 flex items-center gap-2 text-sm text-fg">
          <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: colours.exp }} />
          {expLabel}
          <span className="text-meta text-muted">{n(expN)}</span>
        </div>
        {row("exp")}
        <div className="mb-1 mt-3 flex items-center gap-2 text-sm text-fg">
          <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: colours.ctrl }} />
          {ctrlLabel}
          <span className="text-meta text-muted">{n(ctrlN)}</span>
        </div>
        {row("ctrl")}
        <div className="mt-1 flex gap-1 font-mono text-[11px] text-faint">
          {phases.map((p, i) => (
            <div key={i} className="min-w-0 truncate text-center" style={{ flex: flex(p) }}>
              {p.kind === "surgery" ? "" : p.weeks != null ? `${p.weeks} wk` : ""}
            </div>
          ))}
        </div>
        </div>
      </div>
      {shown == null ? (
        <p className="text-meta text-faint">Select a block for its doses.</p>
      ) : (
        <PhaseDoses
          phase={phases[shown]}
          index={shown}
          expLabel={expLabel}
          ctrlLabel={ctrlLabel}
          colours={colours}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}

/** One phase's full regimen, both arms side by side: where they share a
 *  backbone, the difference is the part in bold. */
function PhaseDoses({
  phase: p,
  index,
  expLabel,
  ctrlLabel,
  colours,
  onClose,
}: {
  phase: Phase;
  index: number;
  expLabel: string;
  ctrlLabel: string;
  colours: ArmColours;
  onClose: () => void;
}) {
  const arm = (label: string, colour: string, add: string | null) => (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5 text-meta text-muted">
        <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ background: colour }} />
        {label}
      </div>
      <p className="mt-0.5 text-sm text-fg">
        {p.kind === "surgery" ? "Surgery" : p.label}
        {add && <span className="font-medium"> + {add}</span>}
      </p>
    </div>
  );
  return (
    <div
      role="region"
      aria-label={`Phase ${index + 1} doses`}
      aria-live="polite"
      className="flex gap-3 rounded-control border border-border bg-surface-2 p-3"
    >
      <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-2">
        {arm(expLabel, colours.exp, p.experimental_add)}
        {arm(ctrlLabel, colours.ctrl, p.control_add)}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <Button variant="ghost" size="icon" aria-label="Close doses" onClick={onClose} className="h-7 w-7">
          <X size={14} aria-hidden />
        </Button>
        {p.weeks != null && <span className="font-mono text-meta text-faint">{p.weeks} wk</span>}
      </div>
    </div>
  );
}

// --- who was enrolled ---------------------------------------------------------------

function Enrolment({ x, ctx }: { x: Extraction; ctx: Ctx }) {
  const [byArm, setByArm] = useState(false);
  const e = x.enrolment;
  const pct = e.n_screened && e.n_randomised ? Math.round((e.n_randomised / e.n_screened) * 100) : null;
  return (
    <Group
      title="Who was enrolled"
      path="enrolment"
      source={e.source}
      ctx={ctx}
      aside={
        <div className="flex overflow-hidden rounded-control border border-border text-meta">
          {(["Overall", "By arm"] as const).map((l, i) => (
            <button
              key={l}
              type="button"
              aria-pressed={byArm === (i === 1)}
              onClick={() => setByArm(i === 1)}
              className={cn("px-2.5 py-1", byArm === (i === 1) ? "bg-surface-2 text-fg" : "text-muted")}
            >
              {l}
            </button>
          ))}
        </div>
      }
    >
      <p className="text-sm text-fg">
        N ={" "}
        <EditableNumber value={e.n_randomised} path="enrolment.n_randomised" ctx={ctx} /> randomised
        {e.n_screened != null && (
          <>
            {" "}
            of <EditableNumber value={e.n_screened} path="enrolment.n_screened" ctx={ctx} /> screened
            {pct != null && ` (${pct}%)`}
          </>
        )}
        {e.n_analysed != null && e.n_analysed !== e.n_randomised && (
          <span className="text-muted"> · analysed {e.n_analysed}</span>
        )}
      </p>
      <div className="flex flex-wrap gap-4 text-meta text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-[3px] bg-surface-2" aria-hidden /> Allowed
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-[3px] border border-dashed border-border-strong" aria-hidden /> Not
          allowed
        </span>
        <span>† allowed with conditions</span>
        {byArm && (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: ctx.colours.exp }} aria-hidden />
            experimental
            <span className="ml-1 h-2.5 w-2.5 rounded-full" style={{ background: ctx.colours.ctrl }} aria-hidden />
            control
          </span>
        )}
      </div>
      <div className="flex flex-col gap-3">
        {Object.keys(DIMENSION_LABELS).map((key) => {
          const i = e.dimensions.findIndex((d) => d.key === key);
          return (
            <DimensionRow
              key={key}
              label={DIMENSION_LABELS[key]}
              d={i >= 0 ? e.dimensions[i] : null}
              path={`enrolment.dimensions.${i}`}
              byArm={byArm}
              ctx={ctx}
            />
          );
        })}
      </div>
    </Group>
  );
}

function DimensionRow({
  label,
  d,
  path,
  byArm,
  ctx,
}: {
  label: string;
  d: Dimension | null;
  path: string;
  byArm: boolean;
  ctx: Ctx;
}) {
  const reported = d?.categories.some(
    (c) => c.overall_pct != null || c.exp_pct != null || c.ctrl_pct != null,
  );
  const allowed = d?.categories.filter((c) => c.eligibility !== "not_allowed") ?? [];
  const top = allowed.reduce<{ label: string; pct: number } | null>(
    (best, c) => (c.overall_pct != null && (!best || c.overall_pct > best.pct) ? { label: c.label, pct: c.overall_pct } : best),
    null,
  );
  return (
    <div className="grid gap-2 sm:grid-cols-[160px_1fr] sm:items-center">
      <div className="min-w-0 text-sm text-fg">
        {label}
        {d?.assay && <span className="block text-meta text-muted">{d.assay}</span>}
        {d?.source && (
          <span className="block">
            <SourceLink source={d.source} ctx={ctx} />
          </span>
        )}
        {reported && allowed.length >= 2 && top && top.pct >= 60 && (
          <span className="block text-meta text-muted">
            Mostly {top.label} ({top.pct}%)
          </span>
        )}
      </div>
      {!d ? (
        <div className="text-meta text-faint">Not reported</div>
      ) : (
        <div className="flex gap-1.5">
          {d.categories.map((c, j) => {
            const no = c.eligibility === "not_allowed";
            const cond = c.eligibility === "conditional";
            const fill = (v: number | null, colour: string, half?: "top" | "bottom") =>
              v != null && (
                <div
                  aria-hidden
                  className={cn("absolute left-0", half === "top" ? "top-0 h-1/2" : half === "bottom" ? "bottom-0 h-1/2" : "inset-y-0")}
                  style={{ width: `${Math.min(100, v)}%`, background: colour, opacity: 0.35 }}
                />
              );
            return (
              <div
                key={j}
                title={
                  no
                    ? `${c.label}: not allowed by the protocol`
                    : cond
                      ? `${c.label}: ${c.condition ?? "allowed with conditions"}`
                      : undefined
                }
                className={cn(
                  "relative flex h-9 min-w-0 flex-1 items-center justify-between gap-1 overflow-hidden rounded-[5px] px-2",
                  no ? "border border-dashed border-border" : "bg-surface-2",
                  cond && "outline outline-1 -outline-offset-1 outline-dashed outline-border-strong",
                )}
              >
                {!no &&
                  (byArm ? (
                    <>
                      {fill(c.exp_pct, ctx.colours.exp, "top")}
                      {fill(c.ctrl_pct, ctx.colours.ctrl, "bottom")}
                    </>
                  ) : (
                    fill(c.overall_pct, ctx.colours.exp)
                  ))}
                <span
                  className={cn(
                    "relative truncate text-[13px]",
                    no ? "text-faint line-through" : "text-fg",
                  )}
                >
                  {c.label}
                  {cond && " †"}
                </span>
                {!no && (
                  <span className="relative text-[13px]">
                    {byArm ? (
                      <>
                        <EditableNumber value={c.exp_pct} path={`${path}.categories.${j}.exp_pct`} ctx={ctx} />
                        {" | "}
                        <EditableNumber value={c.ctrl_pct} path={`${path}.categories.${j}.ctrl_pct`} ctx={ctx} />
                      </>
                    ) : (
                      <EditableNumber value={c.overall_pct} path={`${path}.categories.${j}.overall_pct`} ctx={ctx} suffix="%" />
                    )}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
