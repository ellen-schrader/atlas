import { Container } from "@/components/landing/PublicChrome";

/** The homogenisation argument, on the imaging ground in both themes: the
 *  `dark` class scopes the dark tokens to this band. The Atlas answer is written
 *  for the page, but every source is a real paper in a lab's library. */
const SOURCES = [
  "Cervilla et al., Genome Biology 2026",
  "Bilous et al., Nature Methods 2026",
  "Chen et al., bioRxiv 2026",
];

function Cite({ n }: { n: number }) {
  return <span className="font-semibold text-accent">[{n}]</span>;
}

export function SameQuestion() {
  return (
    <section className="dark bg-surface text-fg">
      <Container className="py-20 sm:py-24">
        <h2 className="max-w-[16em] text-balance text-3xl font-bold leading-[1.08] tracking-[-0.03em] sm:text-[2.75rem]">
          Ask Claude the same question twice.
        </h2>
        <p className="mt-3.5 text-lg text-muted">Once on its own, once with your lab’s library.</p>
        <p className="mt-10 text-xl leading-snug sm:text-[22px]">
          “Which spatial transcriptomics platform should we use for our tumour samples?”
        </p>

        <div className="mt-7 grid items-start gap-6 lg:grid-cols-2">
          <figure>
            <p className="mb-3 text-sm font-semibold text-muted">Claude on its own</p>
            <div className="rounded-card border border-border bg-surface-2 p-5 text-base leading-relaxed text-muted">
              Visium, Xenium and CosMx are widely used. The best choice depends on resolution, gene
              panel, tissue type and budget.
            </div>
            <figcaption className="mt-2.5 text-sm text-muted">Sound advice, and the same for every lab.</figcaption>
          </figure>
          <figure>
            <p className="mb-3 text-sm font-semibold text-accent">Claude with your lab’s Atlas</p>
            <div className="flex flex-col gap-3.5 rounded-card border border-border-strong bg-surface-2 p-5">
              <p className="text-base leading-relaxed">
                Start with the six-cancer platform comparison your lab saved <Cite n={1} />. If you
                choose Xenium, the lab also kept a study of its signal contamination <Cite n={2} /> and a
                new preprint on technical biases in imaging platforms <Cite n={3} />.
              </p>
              <ol className="flex flex-col gap-1 text-[13px] leading-snug text-muted">
                {SOURCES.map((s, i) => (
                  <li key={s}>
                    [{i + 1}] {s}
                  </li>
                ))}
              </ol>
            </div>
            <figcaption className="mt-2.5 text-sm text-muted">Each source opens in Atlas.</figcaption>
          </figure>
        </div>
        <p className="mt-7 text-[13px] text-muted">Example answer, built from papers in a real lab’s library.</p>
      </Container>
    </section>
  );
}
