import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Loader2, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { ApiError, type CitedElement, type CitedPart, fetchCited } from "@/lib/api";
import { type Source, type TrialSource, openSourceFile, pmcUrl } from "@/lib/extraction";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/** What an extracted value's source points at, beside the values: each part
 *  of its "where" ("Results (Patient disposition); Table 1 (ECOG PS)") shown
 *  as the table, figure or section it names, the named rows marked. Not
 *  modal: the values stay readable and clickable, so a number can be checked
 *  against its table and corrected without closing it. */
export function SourcePanel({
  trialId,
  source,
  doc,
  onClose,
}: {
  trialId: string;
  source: Source;
  /** The file, or null when it was removed after the extraction. */
  doc: TrialSource | null;
  onClose: () => void;
}) {
  const { team } = useAppContext();
  const toast = useToast();
  const closeRef = useRef<HTMLButtonElement>(null);
  const lastFocused = useRef<Element | null>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    lastFocused.current = document.activeElement;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (lastFocused.current instanceof HTMLElement) lastFocused.current.focus();
    };
  }, []);

  const cited = useQuery({
    queryKey: ["cited", team.id, trialId, doc?.id, source.where],
    queryFn: () => fetchCited(team.id, trialId, doc!.id, source.where),
    enabled: !!doc && doc.media_type === "application/xml" && !!source.where.trim(),
    staleTime: Infinity,
    retry: (n, e) => !(e instanceof ApiError && (e.status ?? 500) < 500) && n < 2,
  });
  const articleUrl = cited.data?.article_url ?? (doc ? pmcUrl(doc) : null);

  // The first marked row, or the first part, in view once it's shown.
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!cited.data) return;
    const mark = body.current?.querySelector("[data-marked]");
    (mark ?? body.current)?.scrollIntoView?.({ block: "center" });
  }, [cited.data]);

  const open = async () => {
    if (!doc) return;
    try {
      await openSourceFile(doc, source.page);
    } catch {
      toast({ message: "Couldn’t open the source." });
    }
  };

  return createPortal(
    <aside
      role="dialog"
      aria-modal="false"
      aria-label="Source"
      className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-border bg-surface shadow-2xl sm:w-[min(38rem,100vw)]"
    >
      <header className="flex items-start gap-3 border-b border-border p-4">
        <div className="min-w-0 flex-1">
          <div className="text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
            Source · Doc {source.doc}
          </div>
          <div className="mt-0.5 text-sm font-semibold text-fg">
            {source.where || "No place given"}
            {source.page && <span className="font-normal text-muted"> · p. {source.page}</span>}
          </div>
          {doc && <div className="truncate text-meta text-muted">{doc.filename}</div>}
        </div>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          aria-label="Close source"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-control text-muted hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <X size={16} aria-hidden />
        </button>
      </header>

      <div ref={body} className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-4">
        {!doc ? (
          <p className="text-sm text-muted">
            That file was removed after the extraction. Check the value against the trial’s papers.
          </p>
        ) : doc.media_type !== "application/xml" ? (
          <p className="text-sm text-muted">
            This source is a PDF: open it{source.page ? ` at page ${source.page}` : ""} to check the
            value.
          </p>
        ) : cited.isLoading ? (
          <p className="flex items-center gap-2 text-sm text-muted">
            <Loader2 size={14} className="animate-spin" aria-hidden /> Finding it in the paper…
          </p>
        ) : cited.error ? (
          <p role="alert" className="text-sm text-danger">
            {cited.error instanceof ApiError && cited.error.status === 422
              ? "This file can’t be read as an article. Open the full paper instead."
              : "Couldn’t load the source. Try again."}
          </p>
        ) : (
          cited.data?.parts.map((p, i) => <Part key={i} part={p} articleUrl={articleUrl} />)
        )}
      </div>

      {doc && (
        <footer className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border p-4 text-sm">
          {articleUrl ? (
            <a
              href={articleUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-accent hover:underline"
            >
              Open the full paper on PMC <ExternalLink size={13} aria-hidden />
            </a>
          ) : (
            <button
              type="button"
              onClick={open}
              className="inline-flex items-center gap-1 text-accent hover:underline"
            >
              {doc.media_type === "application/pdf" && source.page
                ? `Open the PDF at page ${source.page}`
                : `Open ${doc.filename}`}{" "}
              <ExternalLink size={13} aria-hidden />
            </button>
          )}
        </footer>
      )}
    </aside>,
    document.body,
  );
}

/** One part of the source and the element it names. */
function Part({ part, articleUrl }: { part: CitedPart; articleUrl: string | null }) {
  const e = part.element;
  if (!e)
    return (
      <section className="flex flex-col gap-1">
        <h3 className="text-sm font-semibold text-fg">{part.part}</h3>
        <p className="text-sm text-muted">
          Couldn’t find this in the paper.{articleUrl ? " Look for it in the full paper." : ""}
        </p>
      </section>
    );
  const anchor = articleUrl && e.id ? `${articleUrl}#${encodeURIComponent(e.id)}` : null;
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <h3 className="min-w-0 flex-1 text-sm font-semibold text-fg">
          {e.kind === "section" ? e.label || part.part : e.label}
          {e.kind === "figure" && part.panel && (
            <span className="font-normal text-muted"> · panel {part.panel}</span>
          )}
        </h3>
        {anchor && (
          <a
            href={anchor}
            target="_blank"
            rel="noopener noreferrer"
            title="Open this part of the paper on PMC"
            className="inline-flex shrink-0 items-center gap-1 text-meta text-muted hover:text-accent"
          >
            On PMC <ExternalLink size={12} aria-hidden />
          </a>
        )}
      </div>
      {e.kind === "table" ? (
        <Table e={e} marked={part.rows} />
      ) : e.kind === "figure" ? (
        <p className="text-sm text-fg">{e.caption}</p>
      ) : (
        <Paragraphs paragraphs={e.paragraphs} />
      )}
    </section>
  );
}

function Table({ e, marked }: { e: CitedElement; marked: number[] }) {
  return (
    <>
      {e.caption && <p className="text-sm text-muted">{e.caption}</p>}
      <div className="overflow-x-auto rounded-control border border-border">
        <table className="w-full border-collapse text-meta">
          <tbody>
            {e.rows.map((row, i) => {
              const on = marked.includes(i);
              return (
                <tr
                  key={i}
                  data-marked={on && i === marked[0] ? "" : undefined}
                  className={cn("border-b border-border last:border-0", on && "bg-accent-weak")}
                >
                  {row.map((c, j) => {
                    const Cell = c.header ? "th" : "td";
                    return (
                      <Cell
                        key={j}
                        colSpan={c.colspan}
                        rowSpan={c.rowspan}
                        className={cn(
                          "px-2 py-1 text-left align-top",
                          c.header ? "font-semibold text-fg" : "text-fg",
                          j > 0 && /^[\d<>≤≥(–-]/.test(c.text) && "font-mono",
                        )}
                      >
                        {c.text}
                      </Cell>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {e.footnotes.length > 0 && (
        <ul className="flex flex-col gap-0.5 text-meta text-faint">
          {e.footnotes.map((f, i) => (
            <li key={i}>{f}</li>
          ))}
        </ul>
      )}
    </>
  );
}

function Paragraphs({ paragraphs }: { paragraphs: string[] }) {
  if (paragraphs.length === 0) return <p className="text-sm text-muted">This section has no text.</p>;
  return (
    <div className="flex flex-col gap-2">
      {paragraphs.map((p, i) =>
        p.startsWith("## ") ? (
          <h4 key={i} className="mt-2 text-meta font-semibold uppercase tracking-eyebrow text-faint">
            {p.slice(3)}
          </h4>
        ) : (
          <p key={i} className="text-sm leading-relaxed text-fg">
            {p}
          </p>
        ),
      )}
    </div>
  );
}
