import { useRef, useState } from "react";
import { ChevronDown, Plus, X } from "lucide-react";

import { useDismissable } from "@/hooks/useDismissable";
import {
  type CompareTrial,
  DIFF_PP,
  HR_PREFERENCE,
  MAX_COMPARE,
  MARKERS,
  type Marker,
  diffItems,
  enrolmentRows,
  hrDomain,
  hrLabel,
  hrOf,
  pcrDelta,
  pcrDomain,
  pcrNotComparable,
  pcrOf,
  sharedHrEndpoint,
  trialColour,
} from "@/lib/compare";
import {
  CONTEXT_LABELS,
  DIMENSION_CATEGORIES,
  DIMENSION_LABELS,
  type Phase,
} from "@/lib/extraction";
import { type SiteCountries, countriesSummary } from "@/lib/trials";
import { cn } from "@/lib/utils";

// What makes trials hard to compare, most consequential first.
const DIFF_KEYS = [
  "pcr_definition",
  "followup",
  "efs_events_counted",
  "post_surgery_therapy",
  "pathology_review",
  "pdl1_assay",
  "enrolment_years",
  "region",
];

/** A trial's mark: its colour and its shape, filled (experimental) or hollow
 *  (control). The shape keeps trials apart without colour. */
export function TrialMark({
  index,
  hollow = false,
  size = 12,
}: {
  index: number;
  hollow?: boolean;
  size?: number;
}) {
  const shape: Marker = MARKERS[index % MARKERS.length];
  const c = trialColour(index);
  const s = size;
  const common = {
    fill: hollow ? "var(--surface)" : c,
    stroke: c,
    strokeWidth: hollow ? 2 : 0,
  };
  return (
    <svg width={s} height={s} viewBox="0 0 12 12" aria-hidden className="shrink-0 overflow-visible">
      {shape === "circle" && <circle cx="6" cy="6" r={hollow ? 5 : 6} {...common} />}
      {shape === "square" && <rect x={hollow ? 1 : 0.5} y={hollow ? 1 : 0.5} width={hollow ? 10 : 11} height={hollow ? 10 : 11} rx="1.5" {...common} />}
      {shape === "diamond" && <path d="M6 0.3 L11.7 6 L6 11.7 L0.3 6 Z" {...common} />}
      {shape === "triangle" && <path d="M6 0.6 L11.6 11 L0.4 11 Z" {...common} />}
    </svg>
  );
}

/** Side-by-side view of 2–4 trials' extracted data. Descriptive only. */
export function CompareView({
  available,
  countries,
}: {
  available: CompareTrial[];
  /** Where each trial has sites (registry), by trial id. */
  countries?: SiteCountries;
}) {
  // Each picked trial holds a slot (0–3): its colour and shape. A slot stays
  // with its trial while it's picked, and a newly added trial takes a free one,
  // so no two trials ever share a mark and none is repainted.
  const [slots, setSlots] = useState<Record<string, number>>(() =>
    Object.fromEntries(available.slice(0, MAX_COMPARE).map((t, i) => [t.id, i])),
  );
  // Trials that left (removed from the lab, extraction cleared) drop out; if
  // fewer than two remain, the free slots are filled from the rest.
  const live: Record<string, number> = {};
  for (const [id, slot] of Object.entries(slots))
    if (available.some((t) => t.id === id)) live[id] = slot;
  for (const t of available) {
    if (Object.keys(live).length >= 2) break;
    if (!(t.id in live)) live[t.id] = freeSlot(live);
  }
  const picked = available.filter((t) => t.id in live).map((t) => t.id);
  const slotOf = (id: string) => live[id] ?? 0;
  const trials = available.filter((t) => t.id in live);
  const add = (id: string) => setSlots({ ...live, [id]: freeSlot(live) });
  const remove = (id: string) => {
    const next = { ...live };
    delete next[id];
    setSlots(next);
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 rounded-card border border-border bg-surface p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-heading font-semibold text-fg">Compare trials</h2>
          <p className="text-meta text-muted">
            Descriptive comparison across trials, not randomised.
          </p>
        </div>
        <TrialPicker
          available={available}
          picked={picked}
          onAdd={add}
          onRemove={remove}
          indexOf={slotOf}
        />
      </div>
      {trials.length < 2 ? (
        <p className="text-sm text-muted">Pick at least two trials with extracted data.</p>
      ) : (
        <>
          {/* What differs first: it says how far the numbers below can be compared. */}
          <Differences trials={trials} indexOf={slotOf} countries={countries} />
          <Results trials={trials} indexOf={slotOf} />
          <Schedules trials={trials} indexOf={slotOf} />
          <EnrolmentTable trials={trials} indexOf={slotOf} />
        </>
      )}
    </div>
  );
}

function freeSlot(taken: Record<string, number>): number {
  const used = new Set(Object.values(taken));
  for (let i = 0; i < MAX_COMPARE; i++) if (!used.has(i)) return i;
  return 0;
}

function TrialPicker({
  available,
  picked,
  onAdd,
  onRemove,
  indexOf,
}: {
  available: CompareTrial[];
  picked: string[];
  onAdd: (id: string) => void;
  onRemove: (id: string) => void;
  indexOf: (id: string) => number;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useDismissable(ref, open, () => setOpen(false));
  const rest = available.filter((t) => !picked.includes(t.id));
  const full = picked.length >= MAX_COMPARE;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm text-muted">Comparing</span>
      {picked.map((id) => {
        const t = available.find((x) => x.id === id);
        if (!t) return null;
        return (
          <span
            key={id}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 py-0.5 pl-2.5 pr-1 text-sm text-fg"
          >
            <TrialMark index={indexOf(id)} size={10} />
            {t.name}
            <button
              type="button"
              aria-label={`Remove ${t.name} from the comparison`}
              disabled={picked.length <= 2}
              onClick={() => onRemove(id)}
              className="grid h-6 w-6 place-items-center rounded-full text-muted hover:text-fg disabled:invisible"
            >
              <X size={13} aria-hidden />
            </button>
          </span>
        );
      })}
      {rest.length > 0 && (
        <div ref={ref} className="relative">
          <button
            type="button"
            aria-expanded={open}
            disabled={full}
            onClick={() => setOpen((o) => !o)}
            className="inline-flex min-h-8 items-center gap-1 rounded-full border border-dashed border-border-strong px-3 text-sm text-muted hover:text-fg disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus size={13} aria-hidden /> {full ? "Add · max 4" : "Add trial"}
            <ChevronDown size={13} aria-hidden />
          </button>
          {open && (
            <ul className="absolute left-0 top-full z-30 mt-1.5 w-56 rounded-card border border-border bg-surface p-1.5 shadow-lg">
              {rest.map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onAdd(t.id);
                      setOpen(false);
                    }}
                    className="flex w-full items-center gap-2 rounded-control px-2 py-1.5 text-left text-sm text-fg hover:bg-surface-2"
                  >
                    {t.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Card({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4 rounded-card border border-border bg-surface p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-heading font-semibold text-fg">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function NameCell({ t, index }: { t: CompareTrial; index: number }) {
  return (
    <span className="flex min-w-0 items-center gap-2 text-sm font-medium text-fg">
      <TrialMark index={index} size={10} />
      <span className="truncate">{t.name}</span>
    </span>
  );
}

// --- treatment schedules ----------------------------------------------------------------

const weeksOf = (p: Phase) => (p.kind === "surgery" ? 3 : (p.weeks ?? 8));

function Schedules({ trials, indexOf }: { trials: CompareTrial[]; indexOf: (id: string) => number }) {
  const [open, setOpen] = useState(false);
  const max = Math.max(...trials.map((t) => t.extraction.schedule.reduce((a, p) => a + weeksOf(p), 0)), 12);
  const ticks = Array.from({ length: Math.floor(max / 12) + 1 }, (_, i) => i * 12);
  return (
    <Card
      title="Treatment schedules"
      aside={
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="text-sm text-accent hover:underline"
        >
          {open ? "Hide" : "Show"}
        </button>
      }
    >
      {open && (
        <div className="overflow-x-auto">
          <div className="min-w-[640px]">
            {trials.map((t) => {
              const exp = t.extraction.arms.find((a) => a.role === "experimental");
              let at = 0;
              return (
                <div key={t.id} className="grid grid-cols-[180px_1fr] items-center gap-3 py-2">
                  <div>
                    <NameCell t={t} index={indexOf(t.id)} />
                    <div className="pl-[18px] font-mono text-meta text-muted">
                      {[
                        t.extraction.design.randomisation_ratio && `R ${t.extraction.design.randomisation_ratio}`,
                        t.extraction.design.blinding,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  </div>
                  <div className="relative h-[52px]" title={exp?.label ?? undefined}>
                    {t.extraction.schedule.map((p, i) => {
                      const left = (at / max) * 100;
                      const width = (weeksOf(p) / max) * 100;
                      at += weeksOf(p);
                      const pos = { left: `${left}%`, width: `calc(${width}% - 3px)` };
                      return (
                        <div key={i}>
                          {p.experimental_add && (
                            <div
                              className="absolute top-0 flex h-4 items-center overflow-hidden whitespace-nowrap rounded-[3px] px-1.5 text-[10px] font-semibold"
                              style={{ ...pos, background: trialColour(indexOf(t.id)), color: "var(--surface)" }}
                              title={`${p.label} + ${p.experimental_add}`}
                            >
                              {p.experimental_add}
                            </div>
                          )}
                          <div
                            className={cn(
                              "absolute top-5 flex h-7 items-center justify-center overflow-hidden whitespace-nowrap rounded-[4px] px-1 text-[11px]",
                              p.kind === "chemotherapy"
                                ? "bg-[var(--ch-off)] text-fg"
                                : p.kind === "surgery"
                                  ? "border border-border-strong text-muted"
                                  : p.kind === "observation"
                                    ? "border border-dashed border-border-strong text-muted"
                                    : "bg-surface-3 text-fg",
                            )}
                            style={pos}
                            title={p.label}
                          >
                            {p.kind === "surgery" ? "Surg." : p.label}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
            <div className="grid grid-cols-[180px_1fr] gap-3">
              <span />
              <div className="relative h-4 font-mono text-[11px] text-faint">
                {ticks.map((w) => (
                  <span key={w} className="absolute -translate-x-1/2" style={{ left: `${(w / max) * 100}%` }}>
                    {w} wk
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

// --- results -------------------------------------------------------------------------------

function Axis({ ticks, pos, label }: { ticks: number[]; pos: (v: number) => number; label: (v: number) => string }) {
  return (
    <div className="relative h-4 font-mono text-[11px] text-faint">
      {ticks.map((v, i) => (
        <span
          key={v}
          className="absolute"
          style={{
            left: `${pos(v)}%`,
            transform: `translateX(${i === 0 ? "0" : i === ticks.length - 1 ? "-100%" : "-50%"})`,
          }}
        >
          {label(v)}
        </span>
      ))}
    </div>
  );
}

function Results({ trials, indexOf }: { trials: CompareTrial[]; indexOf: (id: string) => number }) {
  const notComparable = pcrNotComparable(trials);
  const shared = sharedHrEndpoint(trials);
  const hrNames = HR_PREFERENCE.filter((n) => trials.some((t) => hrOf(t.extraction, n)));
  const [hrName, setHrName] = useState<string | null>(shared);
  const hrPick = hrName && hrNames.includes(hrName) ? hrName : shared;

  // pCR axis: the data's range, padded to tens.
  const pcrs = trials.map((t) => pcrOf(t.extraction));
  const pv = pcrs.flatMap((e) => (e ? [e.exp_value!, e.ctrl_value!] : []));
  const [lo, hi] = pcrDomain(pv);
  const pP = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const pTicks = Array.from({ length: (hi - lo) / 10 + 1 }, (_, i) => lo + i * 10).filter((_, i, a) => a.length < 8 || i % 2 === 0);

  // HR axis: log scale around 1.
  const hrs = trials.map((t) => (hrPick ? hrOf(t.extraction, hrPick) : null));
  const hv = hrs.flatMap((e) => (e ? [e.hr!, e.hr_ci_low ?? e.hr!, e.hr_ci_high ?? e.hr!] : []));
  const [hLo, hHi] = hrDomain(hv);
  const hP = (v: number) => ((Math.log(v) - Math.log(hLo)) / (Math.log(hHi) - Math.log(hLo))) * 100;
  const hTicks = [0.25, 0.5, 1, 2, 4].filter((v) => v >= hLo && v <= hHi);

  const row = (t: CompareTrial, plot: React.ReactNode, value: React.ReactNode) => (
    <div key={t.id} className="grid grid-cols-[150px_1fr_120px] items-center gap-3 py-1.5">
      <NameCell t={t} index={indexOf(t.id)} />
      <div className="relative h-7">{plot}</div>
      <div className="text-right font-mono text-sm text-fg">{value}</div>
    </div>
  );

  return (
    <Card
      title="Results"
      aside={
        <span className="flex flex-wrap items-center gap-3 text-meta text-muted">
          <span className="inline-flex items-center gap-1">
            <TrialMark index={0} hollow size={10} /> control
          </span>
          <span className="inline-flex items-center gap-1">
            <TrialMark index={0} size={10} /> experimental
          </span>
          <span>dashed = not directly comparable</span>
        </span>
      }
    >
      <div className="grid gap-8 lg:grid-cols-2">
        <div>
          <h4 className="text-sm font-semibold text-fg">pCR rate</h4>
          <div className="mt-2">
            {trials.map((t, k) => {
              const e = pcrs[k];
              const i = indexOf(t.id);
              if (!e) return row(t, <span className="text-meta text-faint">Not reported</span>, "—");
              const [c, x] = [e.ctrl_value!, e.exp_value!];
              const dashed = notComparable.has(k);
              const d = pcrDelta(e);
              const tip = `${t.name}: control ${c}%, experimental ${x}% (${d >= 0 ? "+" : ""}${d} pp)${dashed ? ". Not directly comparable: pCR defined differently" : ""}`;
              return row(
                t,
                <div className="absolute inset-0" title={tip}>
                  <div
                    className="absolute top-1/2"
                    style={{
                      left: `${pP(Math.min(c, x))}%`,
                      width: `${Math.abs(pP(x) - pP(c))}%`,
                      borderTop: `2px ${dashed ? "dashed" : "solid"} ${trialColour(i)}`,
                      opacity: dashed ? 1 : 0.6,
                    }}
                  />
                  <span className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2" style={{ left: `${pP(c)}%` }}>
                    <TrialMark index={i} hollow size={13} />
                  </span>
                  <span className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2" style={{ left: `${pP(x)}%` }}>
                    <TrialMark index={i} size={13} />
                  </span>
                </div>,
                <span className={dashed ? "text-muted underline decoration-dotted" : undefined} title={dashed ? tip : undefined}>
                  {d >= 0 ? "+" : ""}
                  {d} pp{dashed ? " †" : ""}
                </span>,
              );
            })}
            <div className="grid grid-cols-[150px_1fr_120px] gap-3">
              <span />
              <Axis ticks={pTicks} pos={pP} label={(v) => `${v}%`} />
              <span />
            </div>
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-sm font-semibold text-fg">Hazard ratio (95% CI)</h4>
            {hrNames.length > 1 ? (
              <select
                value={hrPick ?? ""}
                onChange={(e) => setHrName(e.target.value)}
                aria-label="Endpoint"
                className="h-8 rounded-md border border-border bg-surface px-2 text-sm text-fg"
              >
                {hrNames.map((n) => (
                  <option key={n} value={n}>
                    {hrLabel(n)}
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-sm text-muted">{hrPick ? hrLabel(hrPick) : ""}</span>
            )}
          </div>
          {!hrPick ? (
            <p className="mt-2 text-sm text-muted">No hazard ratios extracted.</p>
          ) : (
            <div className="mt-2">
              {trials.map((t, k) => {
                const e = hrs[k];
                const i = indexOf(t.id);
                if (!e) return row(t, <span className="text-meta text-faint">Not reported</span>, "—");
                const ci = e.hr_ci_low != null && e.hr_ci_high != null;
                const tip = `${t.name}: ${hrLabel(hrPick)} HR ${e.hr}${ci ? ` (${e.hr_ci_low}–${e.hr_ci_high})` : ""} · ${e.role.replace("_", "-")}`;
                return row(
                  t,
                  <div className="absolute inset-0" title={tip}>
                    <div className="absolute inset-y-0 w-px bg-border-strong" style={{ left: `${hP(1)}%` }} />
                    {ci && (
                      <div
                        className="absolute top-1/2 h-[2px] -translate-y-1/2"
                        style={{
                          left: `${hP(e.hr_ci_low!)}%`,
                          width: `${hP(e.hr_ci_high!) - hP(e.hr_ci_low!)}%`,
                          background: trialColour(i),
                        }}
                      />
                    )}
                    <span className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2" style={{ left: `${hP(e.hr!)}%` }}>
                      <TrialMark index={i} size={13} />
                    </span>
                  </div>,
                  <span title={tip}>{e.hr}</span>,
                );
              })}
              <div className="grid grid-cols-[150px_1fr_120px] gap-3">
                <span />
                <div>
                  <Axis ticks={hTicks} pos={hP} label={(v) => String(v)} />
                  <div className="mt-1 text-meta text-muted" style={{ paddingLeft: 0 }}>
                    ← favours experimental
                  </div>
                </div>
                <span />
              </div>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

// --- what differs ------------------------------------------------------------------------------

function Differences({
  trials,
  indexOf,
  countries,
}: {
  trials: CompareTrial[];
  indexOf: (id: string) => number;
  countries?: SiteCountries;
}) {
  const [all, setAll] = useState(false);
  // Where they enrolled, from the registry: standard of care and patients vary
  // by country, so it bears on how comparable the results are.
  const where = countries ? trials.map((t) => countries[t.id] ?? []) : null;
  const shared =
    where && where.every((w) => w.length)
      ? where
          .map((w) => new Set(w.map((c) => c.country)))
          .reduce((a, b) => new Set([...a].filter((x) => b.has(x))))
      : null;
  const items = diffItems(trials, DIFF_KEYS);
  // Real disagreements first, then items only some trials report; items no
  // trial reports are just listed at the end.
  const notable = [
    ...items.filter((i) => i.status === "differs"),
    ...items.filter((i) => i.status === "unknown" && i.groups.length > 0),
  ];
  const missing = items.filter((i) => i.groups.length === 0);
  const same = items.filter((i) => i.status === "same");
  const shown = all ? notable : notable.slice(0, 3);
  return (
    <Card title="What differs">
      {where && (
        <div className="grid gap-2 sm:grid-cols-[180px_1fr]">
          <span className="text-sm text-fg">
            Countries
            <span className="block text-meta text-muted">with trial sites</span>
          </span>
          <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap gap-1.5">
              {trials.map((t, k) => (
                <span
                  key={t.id}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-meta text-fg"
                  title={where[k].map((c) => `${c.country} (${c.sites})`).join(", ") || "No sites listed"}
                >
                  <TrialMark index={indexOf(t.id)} size={9} />
                  {t.name}: {countriesSummary(where[k])}
                </span>
              ))}
            </div>
            {shared && (
              <p className="text-meta text-muted">
                {shared.size === 0
                  ? "No country in common."
                  : `In common: ${[...shared].slice(0, 6).join(", ")}${shared.size > 6 ? ` +${shared.size - 6}` : ""}`}
              </p>
            )}
          </div>
        </div>
      )}
      {notable.length === 0 ? (
        <p className="text-sm text-muted">No differences in what was extracted.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {shown.map((item) => {
            const unknown = item.values.flatMap((v, k) => (v ? [] : [k]));
            return (
              <li key={item.key} className="grid gap-2 sm:grid-cols-[180px_1fr]">
                <span className="text-sm text-fg">{CONTEXT_LABELS[item.key] ?? item.key}</span>
                <div className="flex flex-wrap gap-1.5">
                  {item.groups.map((g) => (
                    <span
                      key={g.value}
                      className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-meta text-fg"
                      title={g.trials.map((k) => trials[k].name).join(", ")}
                    >
                      {g.trials.map((k) => (
                        <TrialMark key={k} index={indexOf(trials[k].id)} size={9} />
                      ))}
                      {g.value}
                    </span>
                  ))}
                  {unknown.length > 0 && (
                    <span className="inline-flex items-center rounded-full border border-dashed border-border-strong px-2.5 py-0.5 text-meta text-faint">
                      not extracted: {unknown.map((k) => trials[k].name).join(", ")}
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {notable.length > 3 && (
        <button type="button" onClick={() => setAll((a) => !a)} className="w-fit text-sm text-accent hover:underline">
          {all ? "Show fewer" : `+${notable.length - 3} more differences`}
        </button>
      )}
      {same.length > 0 && (
        <p className="text-meta text-muted">
          Same in all:{" "}
          {same.map((i) => `${CONTEXT_LABELS[i.key] ?? i.key}: ${i.values.find(Boolean)}`).join(" · ")}
        </p>
      )}
      {missing.length > 0 && (
        <p className="text-meta text-faint">
          Not extracted for any of these trials:{" "}
          {missing.map((i) => CONTEXT_LABELS[i.key] ?? i.key).join(", ")}
        </p>
      )}
    </Card>
  );
}

// --- enrolment -------------------------------------------------------------------------------------

function EnrolmentTable({ trials, indexOf }: { trials: CompareTrial[]; indexOf: (id: string) => number }) {
  const [all, setAll] = useState(false);
  const rows = enrolmentRows(trials, DIMENSION_CATEGORIES);
  const reported = rows.filter((r) => r.cells.some((c) => c.state !== "not_reported"));
  const shown = all ? reported : reported.filter((r) => r.differs);
  return (
    <Card
      title="Who was enrolled · % of each trial"
      aside={
        <span className="text-meta text-muted">
          ↑↓ differs ≥{DIFF_PP} pp from the other trials · dashed: not allowed
        </span>
      }
    >
      {shown.length === 0 ? (
        <p className="text-sm text-muted">
          {reported.length ? `No category differs by ${DIFF_PP} pp or more.` : "No baseline data extracted."}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="text-left">
                <th className="py-2 pr-3 font-normal text-muted">
                  <span className="sr-only">Category</span>
                </th>
                {trials.map((t) => (
                  <th key={t.id} className="px-1 py-2 font-medium">
                    <NameCell t={t} index={indexOf(t.id)} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((r, k) => {
                const firstOfDim = k === 0 || shown[k - 1].dimension !== r.dimension;
                return (
                  <tr key={`${r.dimension}:${r.category}`} className={firstOfDim && k ? "border-t border-border" : undefined}>
                    <td className="py-1 pr-3 text-muted">
                      {firstOfDim && <span className="text-fg">{DIMENSION_LABELS[r.dimension]} </span>}
                      {r.category}
                    </td>
                    {r.cells.map((c, j) => {
                      const t = trials[j];
                      if (c.state === "not_allowed")
                        return (
                          <td key={t.id} className="px-1 py-1">
                            <div
                              className="h-7 rounded-[5px] border border-dashed border-border px-2 text-[11px] leading-7 text-faint"
                              title={`${t.name}: ${r.category} not allowed by the protocol`}
                            >
                              not allowed
                            </div>
                          </td>
                        );
                      if (c.state === "not_reported")
                        return (
                          <td key={t.id} className="px-1 py-1 text-[11px] text-faint" title={`${t.name}: not reported`}>
                            n/r
                          </td>
                        );
                      return (
                        <td key={t.id} className="px-1 py-1">
                          <div
                            className="relative h-7 overflow-hidden rounded-[5px] bg-surface-2"
                            title={`${t.name}: ${c.pct}% ${r.category}${c.othersMean != null ? ` · others average ${c.othersMean}%` : ""}`}
                          >
                            <div
                              aria-hidden
                              className="absolute inset-y-0 left-0"
                              style={{ width: `${Math.min(100, c.pct)}%`, background: trialColour(indexOf(t.id)), opacity: 0.3 }}
                            />
                            <span
                              className={cn(
                                "relative px-2 font-mono text-[12px] leading-7 text-fg",
                                c.flag && "font-bold",
                              )}
                            >
                              {c.flag === "up" ? "↑ " : c.flag === "down" ? "↓ " : ""}
                              {c.pct}%
                            </span>
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {reported.length > 0 && (
        <button type="button" onClick={() => setAll((a) => !a)} className="w-fit text-sm text-accent hover:underline">
          {all ? "Show only differences" : `Show all ${reported.length} rows`}
        </button>
      )}
    </Card>
  );
}
