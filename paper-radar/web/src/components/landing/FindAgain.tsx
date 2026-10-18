import { type ReactNode, useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";

import { Container } from "@/components/landing/PublicChrome";
import { type RevealState, useInViewOnce } from "@/hooks/useInViewOnce";

/** Real output from a lab's library via the Atlas connector (2026-10-18): the top
 *  four semantic results for QUERY, and similar_papers on ANCHOR. `match` marks a
 *  word that matched by meaning rather than spelling. */
const QUERY = "immunosuppressive macrophages";
const RESULTS = [
  { title: "Explainable machine learning-guided integrated multiomics analysis reveals macrophage-driven immune suppression in breast cancer", venue: "Nat Commun", year: 2026 },
  { title: "Chemokine-defined macrophage niches establish spatial organization of tumor immunity", venue: "Nat Immunol", year: 2026 },
  { title: "Inflammation- and resolution-programmed myeloid circuits govern therapeutic resistance in epithelial and mesenchymal triple-negative breast cancer", venue: "J Clin Invest", year: 2026, match: "myeloid" },
  { title: "CD49a+ NK cells promote M2 polarization and are associated with poor pathological response in NSCLC", venue: "Sci Rep", year: 2026, match: "M2" },
];
const ANCHOR = {
  title: "Resolving sensitivity, specificity and signal contamination in Xenium spatial transcriptomics",
  venue: "Nature Methods",
  year: 2026,
};
const SIMILAR = [
  { title: "DeSpotX: Identifiability-Based Decontamination for Spatial Transcriptomics", venue: "bioRxiv", year: 2026 },
  { title: "Impact and correction of segmentation errors in spatial transcriptomics", venue: "Nature Genetics", year: 2026 },
  { title: "A technical comparison of spatial transcriptomics platforms across six cancer types", venue: "Genome Biology", year: 2026 },
  { title: "ResolVI: addressing noise and bias in spatial transcriptomics", venue: "Nature Methods", year: 2026 },
];

type Paper = { title: string; venue: string; year: number; match?: string };

export function FindAgain() {
  return (
    <section className="border-y border-border bg-surface">
      <Container className="py-20 sm:py-24">
        <h2 className="max-w-[16em] text-balance text-3xl font-bold leading-[1.08] tracking-[-0.03em] sm:text-[2.75rem]">
          Find it again, even without the title.
        </h2>
        <p className="mt-3.5 text-lg text-muted">Search by meaning, or ask for more like a paper you liked.</p>
        <div className="mt-11 grid items-start gap-6 lg:grid-cols-2">
          <SearchPanel />
          <SimilarPanel />
        </div>
      </Container>
    </section>
  );
}

function Panel({ label, children }: { label: string; children: ReactNode }) {
  return (
    <figure className="flex flex-col gap-3.5 rounded-card border border-border bg-bg p-[18px]">
      <figcaption className="text-sm font-semibold text-accent">{label}</figcaption>
      {children}
    </figure>
  );
}

function PaperLine({ paper, index, marked = true }: { paper: Paper; index: number; marked?: boolean }) {
  const { title, match } = paper;
  const at = match ? title.indexOf(match) : -1;
  return (
    <li className="reveal-item flex flex-col gap-0.5 px-0.5" style={{ animationDelay: `${index * 90}ms` }}>
      <span className="text-sm font-semibold leading-snug">
        {at < 0 ? (
          title
        ) : (
          <>
            {title.slice(0, at)}
            <mark className={marked ? "rounded bg-accent-weak px-0.5 text-fg" : "bg-transparent text-fg"}>
              {match}
            </mark>
            {title.slice(at + match!.length)}
          </>
        )}
      </span>
      <span className="text-xs text-muted">
        <span className="font-semibold uppercase tracking-wide">{paper.venue}</span> · {paper.year}
      </span>
    </li>
  );
}

/** Types the query in once the panel is on screen, then reveals the results. */
function SearchPanel() {
  const ref = useRef<HTMLDivElement>(null);
  const reveal = useInViewOnce(ref);
  const [typed, setTyped] = useState(0);
  const typing = reveal === "played" && typed < QUERY.length;
  const results: RevealState = reveal === "static" ? "static" : typed < QUERY.length ? "armed" : "played";

  useEffect(() => {
    if (!typing) return;
    const t = window.setTimeout(() => setTyped((n) => n + 1), typed === 0 ? 250 : 55);
    return () => window.clearTimeout(t);
  }, [typing, typed]);

  const shown = reveal === "static" ? QUERY : QUERY.slice(0, typed);
  return (
    <div ref={ref}>
      <Panel label="Search by meaning">
        <div className="flex items-center gap-2.5 rounded-control border border-border-strong bg-surface px-3.5 py-2.5 text-[15px]">
          <Search size={16} className="shrink-0 text-muted" aria-hidden="true" />
          <span>
            <span className="sr-only">Search: {QUERY}</span>
            <span aria-hidden="true">{shown}</span>
            {typing && <span className="reveal-caret ml-px inline-block h-[1.1em] w-[1.5px] translate-y-[0.2em] bg-current" />}
          </span>
        </div>
        <ul data-reveal={results} className="flex flex-col gap-3.5">
          {RESULTS.map((p, i) => (
            <PaperLine key={p.title} paper={p} index={i} marked={results !== "armed"} />
          ))}
          <li className="reveal-item px-0.5 text-[13px] text-muted" style={{ animationDelay: "500ms" }}>
            Also finds papers that only say “myeloid” or “M2”.
          </li>
        </ul>
      </Panel>
    </div>
  );
}

function SimilarPanel() {
  const ref = useRef<HTMLDivElement>(null);
  const reveal = useInViewOnce(ref);
  return (
    <div ref={ref}>
      <Panel label="More like this">
        <div className="flex flex-col gap-0.5 rounded-control border border-border-strong bg-surface px-3.5 py-2.5">
          <span className="text-sm font-semibold leading-snug">{ANCHOR.title}</span>
          <span className="text-xs text-muted">
            <span className="font-semibold uppercase tracking-wide">{ANCHOR.venue}</span> · {ANCHOR.year}
          </span>
        </div>
        <ul data-reveal={reveal} className="flex flex-col gap-3.5">
          {SIMILAR.map((p, i) => (
            <PaperLine key={p.title} paper={p} index={i} />
          ))}
        </ul>
      </Panel>
    </div>
  );
}
