import { PreprintBadge } from "@/components/PreprintBadge";
import { isPreprintVenue } from "@/lib/preprint";
import { Container, HEADLINE, SignupLink, TAGLINE } from "@/components/landing/PublicChrome";

/** Real papers from a lab's library (approved for the page, 2026-10-18). The lab
 *  itself is never named. */
const PAPERS = [
  { title: "On technical biases in imaging spatial transcriptomics", venue: "bioRxiv", year: 2026 },
  { title: "Identifying 3D signal overlaps in spatial transcriptomics data with ovrlpy", venue: "Nature Biotechnology", year: 2026 },
  { title: "Segment anything in pathology images with natural language", venue: "Nature Computational Science", year: 2026 },
  { title: "Spatially-smoothed quantification improves cell typing in imaging mass cytometry datasets", venue: "bioRxiv", year: 2025 },
  { title: "Embracing macrophage complexity for research and translation", venue: "Immunity", year: 2026 },
];

export function Hero() {
  return (
    <Container className="grid items-center gap-16 py-20 sm:py-24 lg:grid-cols-2">
      <div>
        <h1 className="text-balance text-4xl font-bold leading-[1.04] tracking-[-0.035em] sm:text-[3.5rem]">
          {HEADLINE}
        </h1>
        <p className="mt-6 max-w-[26em] text-lg leading-relaxed text-muted sm:text-xl">
          {TAGLINE}
        </p>
        <div className="mt-9 flex flex-wrap items-center gap-x-5 gap-y-3">
          <SignupLink />
          <span className="text-sm text-muted">Free during beta</span>
        </div>
      </div>

      {/* The Papers list drawn like PaperListRow. Not that component: it needs a
          full PaperPost and an onOpen, and these rows are a picture, not links. */}
      <figure
        className="overflow-hidden rounded-card border border-border bg-surface shadow-[0_30px_60px_-30px_rgba(18,24,26,0.25)] dark:shadow-[0_30px_60px_-30px_rgba(0,0,0,0.8)]"
        aria-label="An example of a lab’s paper library"
      >
        <div className="flex items-center gap-3 border-b border-border px-4 py-3.5">
          <span className="text-[15px] font-bold">Library</span>
          <span className="ml-auto w-56 max-w-[50%] rounded-control bg-surface-2 px-3 py-2 text-sm text-muted">
            Search
          </span>
        </div>
        <ul>
          {PAPERS.map((p) => (
            <li
              key={p.title}
              className="flex items-center gap-3 border-b border-border px-4 py-3.5 last:border-b-0"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-fg">{p.title}</span>
                <span className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted">
                  <span className="font-semibold uppercase tracking-wide">{p.venue}</span>
                  <span>· {p.year}</span>
                  {isPreprintVenue(p.venue) && <PreprintBadge />}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </figure>
    </Container>
  );
}
