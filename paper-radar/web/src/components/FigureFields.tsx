import type { ReactNode } from "react";

import { CategoryPicker } from "@/components/CategoryPicker";
import { PaperPicker, type PickedPaper } from "@/components/PaperPicker";
import { Input } from "@/components/ui/input";

/** The metadata fields shared by the figure upload dialog and the inline edit
 *  form: title, caption, category, and an optional linked paper. */
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

      <Field label="Category">
        <CategoryPicker teamId={teamId} value={category} onChange={onCategory} />
      </Field>

      <Field label="Link a paper (optional)">
        <PaperPicker teamId={teamId} value={paper} onChange={onPaper} />
      </Field>
    </>
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
