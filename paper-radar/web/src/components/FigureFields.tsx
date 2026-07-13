import { type ReactNode, useState } from "react";

import { CategoryPicker } from "@/components/CategoryPicker";
import { PaperPicker, type PickedPaper } from "@/components/PaperPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { lookupLicense, resolveDoi } from "@/lib/licenses";
import type { Figure } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The metadata fields shared by the figure upload dialog and the inline edit
 *  form: title, caption, origin (own vs third-party), category, an optional
 *  linked paper, and — for third-party images — source / licence / attribution. */
export function FigureFields({
  teamId,
  title,
  onTitle,
  caption,
  onCaption,
  category,
  onCategory,
  paper,
  onPaper,
  origin,
  onOrigin,
  sourceUrl,
  onSourceUrl,
  license,
  onLicense,
  attribution,
  onAttribution,
}: {
  teamId: string;
  title: string;
  onTitle: (v: string) => void;
  caption: string;
  onCaption: (v: string) => void;
  category: string;
  onCategory: (v: string) => void;
  paper: PickedPaper | null;
  onPaper: (v: PickedPaper | null) => void;
  // "style_card" only reaches this form via the edit path (cards are created over
  // MCP); the toggle is then replaced by a static note and origin passes through.
  origin: Figure["origin"];
  onOrigin: (v: "own" | "third_party") => void;
  sourceUrl: string;
  onSourceUrl: (v: string) => void;
  license: string;
  onLicense: (v: string) => void;
  attribution: string;
  onAttribution: (v: string) => void;
}) {
  return (
    <>
      <Field label="Title">
        <Input
          value={title}
          onChange={(e) => onTitle(e.target.value)}
          placeholder="e.g. Diverging expression heatmap"
        />
      </Field>

      <Field label="Caption">
        <Input
          value={caption}
          onChange={(e) => onCaption(e.target.value)}
          placeholder="What makes this figure worth learning from?"
        />
      </Field>

      <Field label="Image origin">
        {origin === "style_card" ? (
          <span className="text-sm text-muted">
            Style card — a synthetic recreation; the origin can't change.
          </span>
        ) : (
          <OriginToggle value={origin} onChange={onOrigin} />
        )}
      </Field>

      <Field label="Category">
        <CategoryPicker teamId={teamId} value={category} onChange={onCategory} />
      </Field>

      <Field label="Link a paper (optional)">
        <PaperPicker teamId={teamId} value={paper} onChange={onPaper} />
      </Field>

      {origin === "third_party" && (
        <ThirdPartyFields
          paperId={paper?.id ?? null}
          sourceUrl={sourceUrl}
          onSourceUrl={onSourceUrl}
          license={license}
          onLicense={onLicense}
          attribution={attribution}
          onAttribution={onAttribution}
        />
      )}
    </>
  );
}

function OriginToggle({
  value,
  onChange,
}: {
  value: "own" | "third_party";
  onChange: (v: "own" | "third_party") => void;
}) {
  const options: { v: "own" | "third_party"; label: string }[] = [
    { v: "own", label: "Our own work" },
    { v: "third_party", label: "Third-party" },
  ];
  return (
    <div className="inline-flex rounded-control border border-border p-0.5">
      {options.map((o) => (
        <button
          key={o.v}
          type="button"
          onClick={() => onChange(o.v)}
          aria-pressed={value === o.v}
          className={cn(
            "rounded-[6px] px-3 py-1.5 text-sm font-medium transition",
            value === o.v ? "bg-accent text-accent-fg" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Provenance for a third-party image: where it came from, its licence (with an
 *  advisory lookup from the linked paper's DOI), and a display credit. */
function ThirdPartyFields({
  paperId,
  sourceUrl,
  onSourceUrl,
  license,
  onLicense,
  attribution,
  onAttribution,
}: {
  paperId: string | null;
  sourceUrl: string;
  onSourceUrl: (v: string) => void;
  license: string;
  onLicense: (v: string) => void;
  attribution: string;
  onAttribution: (v: string) => void;
}) {
  const [looking, setLooking] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function look() {
    setLooking(true);
    setNote(null);
    try {
      const doi = await resolveDoi(sourceUrl, paperId);
      if (!doi) {
        setNote("No DOI found — link a paper or paste a DOI/URL first.");
        return;
      }
      const found = await lookupLicense(doi);
      if (found) {
        onLicense(found);
        setNote(`Found “${found}” for the article — confirm it covers this figure.`);
      } else {
        setNote("No licence recorded for that DOI. Enter it manually.");
      }
    } catch {
      setNote("Couldn’t reach the licence service.");
    } finally {
      setLooking(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-card border border-border bg-surface-2 p-4">
      <p className="text-xs text-muted">
        Style inspiration only — record where it came from. We derive style, not reproductions.
      </p>
      <Field label="Source URL / DOI">
        <Input
          value={sourceUrl}
          onChange={(e) => onSourceUrl(e.target.value)}
          placeholder="https://doi.org/10.1016/…"
        />
      </Field>
      <Field label="Licence">
        <div className="flex gap-2">
          <Input
            value={license}
            onChange={(e) => onLicense(e.target.value)}
            placeholder="e.g. cc-by"
          />
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="whitespace-nowrap"
            onClick={look}
            disabled={looking}
          >
            {looking ? "…" : "Look up"}
          </Button>
        </div>
      </Field>
      <Field label="Attribution">
        <Input
          value={attribution}
          onChange={(e) => onAttribution(e.target.value)}
          placeholder="e.g. Okafor & Petrov, Cell 2022"
        />
      </Field>
      {note && <p className="text-xs text-muted">{note}</p>}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-eyebrow font-bold uppercase tracking-eyebrow text-muted">{label}</span>
      {children}
    </div>
  );
}
