import { useRef, useState } from "react";
import { Check, CheckSquare, ChevronDown, Copy, Download, X } from "lucide-react";

import { useCopyToClipboard } from "@/hooks/useCopyToClipboard";
import { useDismiss } from "@/hooks/useDismiss";
import type { Selection } from "@/hooks/useSelection";
import {
  type ExportFormat,
  type ExportPaper,
  exportFilename,
  FORMAT_META,
  formatPapers,
  downloadText,
} from "@/lib/paperExport";
import { cn } from "@/lib/utils";

const FORMATS: ExportFormat[] = ["markdown", "text", "bibtex"];

/** The multi-select export UI for a list: the spacer that keeps the last row clear
 *  of the floating bar, plus the bar itself. Renders nothing until select mode is on.
 *  `items` is the list as currently shown; select-all and the count act on it. */
export function SelectionExportBar<T>({
  selection,
  items,
  idOf,
  toExport,
  heading,
}: {
  selection: Selection;
  items: T[];
  idOf: (item: T) => string;
  toExport: (item: T) => ExportPaper;
  heading?: string;
}) {
  if (!selection.selecting) return null;
  const ids = items.map(idOf);
  const selected = items.filter((it) => selection.isSelected(idOf(it))).map(toExport);
  const allSelected = ids.length > 0 && ids.every((id) => selection.isSelected(id));

  return (
    <>
      {/* Space so the floating bar never hides the last row of the list. */}
      <div aria-hidden className="h-16" />
      <ExportBar
        papers={selected}
        totalCount={ids.length}
        allSelected={allSelected}
        onSelectAll={() => selection.selectAll(ids)}
        onClear={selection.clear}
        onExit={selection.stop}
        heading={heading}
      />
    </>
  );
}

/** Toolbar button that enters/leaves multi-select mode. */
export function SelectToggle({ selection, className }: { selection: Selection; className?: string }) {
  return (
    <button
      type="button"
      onClick={() => (selection.selecting ? selection.stop() : selection.start())}
      aria-pressed={selection.selecting}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-control border px-3 text-sm font-medium transition",
        selection.selecting
          ? "border-accent/50 bg-accent-weak text-accent"
          : "border-border text-muted hover:border-border-strong hover:text-fg",
        className,
      )}
    >
      <CheckSquare size={14} />
      Select
    </button>
  );
}

/** The floating action bar: count, select-all/clear, and the export popover. */
function ExportBar({
  papers,
  totalCount,
  allSelected,
  onSelectAll,
  onClear,
  onExit,
  heading,
}: {
  /** The currently-selected papers, resolved to their exportable fields. */
  papers: ExportPaper[];
  /** How many papers are selectable in the current view. */
  totalCount: number;
  allSelected: boolean;
  onSelectAll: () => void;
  onClear: () => void;
  onExit: () => void;
  heading?: string;
}) {
  const n = papers.length;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-5 z-40 flex justify-center px-4">
      <div className="pointer-events-auto flex items-center gap-2 rounded-full border border-border bg-surface/95 py-2 pl-4 pr-2 shadow-xl backdrop-blur">
        <span className="text-sm font-medium text-fg tabular-nums">
          {n > 0 ? `${n} selected` : "Select papers"}
        </span>

        <span className="h-4 w-px bg-border" aria-hidden />

        <button
          type="button"
          onClick={allSelected ? onClear : onSelectAll}
          className="rounded-full px-2.5 py-1 text-xs font-medium text-muted transition hover:bg-surface-2 hover:text-fg"
        >
          {allSelected ? "Clear" : `Select all ${totalCount}`}
        </button>

        <ExportMenu papers={papers} heading={heading} />

        <button
          type="button"
          onClick={onExit}
          aria-label="Done selecting"
          className="grid h-8 w-8 place-items-center rounded-full text-muted transition hover:bg-surface-2 hover:text-fg"
        >
          <X size={16} />
        </button>
      </div>
    </div>
  );
}

function ExportMenu({ papers, heading }: { papers: ExportPaper[]; heading?: string }) {
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<ExportFormat>("markdown");
  const [abstracts, setAbstracts] = useState(false);
  const { copied, copy: copyToClipboard } = useCopyToClipboard(1600);
  const ref = useRef<HTMLDivElement>(null);

  const n = papers.length;
  const disabled = n === 0;

  useDismiss(ref, open, () => setOpen(false));

  async function copy() {
    const ok = await copyToClipboard(formatPapers(papers, format, { abstracts, heading }));
    // Clipboard blocked (insecure origin / denied) — fall back to a download so the
    // user still gets their list out.
    if (!ok) download();
  }

  function download() {
    const text = formatPapers(papers, format, { abstracts, heading });
    downloadText(exportFilename(format, n, heading), text, FORMAT_META[format].mime);
    setOpen(false);
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded-full bg-accent px-3.5 text-sm font-medium text-accent-fg transition",
          "hover:brightness-110 disabled:opacity-40 disabled:hover:brightness-100",
        )}
      >
        <Download size={14} />
        Export
        <ChevronDown size={14} className={cn("transition", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute bottom-full right-0 mb-2 w-72 overflow-hidden rounded-card border border-border bg-surface shadow-xl">
          <div className="border-b border-border px-4 py-2.5 text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
            Export {n} paper{n === 1 ? "" : "s"}
          </div>

          <div className="flex flex-col p-1.5">
            {FORMATS.map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFormat(f)}
                className={cn(
                  "flex items-center gap-3 rounded-control px-2.5 py-2 text-left transition hover:bg-surface-2",
                  format === f && "bg-surface-2",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "grid h-4 w-4 shrink-0 place-items-center rounded-full border",
                    format === f ? "border-accent" : "border-border-strong",
                  )}
                >
                  {format === f && <span className="h-2 w-2 rounded-full bg-accent" />}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-fg">{FORMAT_META[f].label}</span>
                  <span className="block text-xs text-muted">{FORMAT_META[f].hint}</span>
                </span>
              </button>
            ))}
          </div>

          <label className="flex cursor-pointer items-center gap-2.5 border-t border-border px-4 py-2.5 text-sm text-fg">
            <span
              className={cn(
                "grid h-4 w-4 shrink-0 place-items-center rounded border transition",
                abstracts ? "border-accent bg-accent text-accent-fg" : "border-border-strong",
              )}
            >
              {abstracts && <Check size={12} strokeWidth={3} />}
            </span>
            <input
              type="checkbox"
              checked={abstracts}
              onChange={(e) => setAbstracts(e.target.checked)}
              className="sr-only"
            />
            Include abstracts
            <span className="ml-auto text-xs text-faint">more detail</span>
          </label>

          <div className="flex gap-1.5 border-t border-border p-1.5">
            <button
              type="button"
              onClick={copy}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-control px-3 py-2 text-sm font-medium text-fg transition hover:bg-surface-2"
            >
              {copied ? (
                <>
                  <Check size={14} className="text-accent" /> Copied
                </>
              ) : (
                <>
                  <Copy size={14} /> Copy
                </>
              )}
            </button>
            <button
              type="button"
              onClick={download}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-control bg-accent px-3 py-2 text-sm font-medium text-accent-fg transition hover:brightness-110"
            >
              <Download size={14} /> Download
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** A selection checkbox for a paper card or list row. Stops propagation so ticking
 *  it never also opens the paper. */
export function SelectCheckbox({
  checked,
  onChange,
  className,
  label = "Select paper",
}: {
  checked: boolean;
  onChange: () => void;
  className?: string;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={cn(
        "grid h-5 w-5 shrink-0 place-items-center rounded-md border transition",
        checked
          ? "border-accent bg-accent text-accent-fg"
          : "border-border-strong bg-surface hover:border-accent",
        className,
      )}
    >
      {checked && <Check size={13} strokeWidth={3} />}
    </button>
  );
}
