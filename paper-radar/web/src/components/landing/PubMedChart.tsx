import { type CSSProperties, useRef } from "react";

import { Container } from "@/components/landing/PublicChrome";
import { useInViewOnce } from "@/hooks/useInViewOnce";

/** Records added to PubMed per calendar year, by Entrez date: an E-utilities
 *  esearch count of `YYYY/01/01:YYYY/12/31[edat]`, taken on 2026-10-18. */
const ADDED = [
  [2000, 499203], [2001, 541676], [2002, 605932], [2003, 610705], [2004, 631542],
  [2005, 691706], [2006, 713247], [2007, 749880], [2008, 794591], [2009, 804856],
  [2010, 839733], [2011, 897957], [2012, 941522], [2013, 998664], [2014, 1068128],
  [2015, 1091650], [2016, 1136715], [2017, 1135713], [2018, 1180956], [2019, 1243065],
  [2020, 1443701], [2021, 1542801], [2022, 1540383], [2023, 1499877], [2024, 1546986],
  [2025, 1700088],
] as const;

const SOURCE_URL =
  "https://pubmed.ncbi.nlm.nih.gov/?term=2025%2F01%2F01%3A2025%2F12%2F31%5Bedat%5D";
const MAX = 1_800_000;
const fmt = (n: number) => n.toLocaleString("en-GB");
/** Year labels sit under their own bar's centre. */
const tickLeft = (i: number) => `${((i + 0.5) / ADDED.length) * 100}%`;

export function PubMedChart() {
  const ref = useRef<HTMLDivElement>(null);
  const reveal = useInViewOnce(ref);
  const last = ADDED.length - 1;

  return (
    <section className="border-t border-border">
      <Container className="py-20 sm:py-24">
        <h2 className="max-w-[16em] text-balance text-3xl font-bold leading-[1.08] tracking-[-0.03em] sm:text-[2.75rem]">
          1.7 million papers were added to PubMed in 2025.
        </h2>
        <p className="mt-3.5 text-lg text-muted">
          More than three times as many as in 2000. No lab can read them all.
        </p>

        <figure className="mt-12">
          <div
            ref={ref}
            data-reveal={reveal}
            role="img"
            aria-label="Bar chart of papers added to PubMed each year, rising from 0.5 million in 2000 to 1.7 million in 2025."
            className="relative flex h-64 items-end gap-0.5 border-b border-border-strong"
          >
            {ADDED.map(([year, n], i) => (
              <div
                key={year}
                title={`${year}: ${fmt(n)} papers`}
                className={`reveal-bar flex-1 rounded-t ${i === last ? "bg-accent" : "bg-[var(--year-4)] dark:bg-[var(--year-3)]"}`}
                style={{ height: `${(n / MAX) * 100}%`, animationDelay: `${i * 28}ms` } as CSSProperties}
              />
            ))}
            <span
              className="absolute left-0 text-[13px] font-semibold tabular-nums text-muted"
              style={{ bottom: `${(ADDED[0][1] / MAX) * 100 + 3}%` }}
            >
              0.5M
            </span>
            <span
              className="reveal-item absolute -top-6 right-0 text-[13px] font-bold tabular-nums text-fg"
              style={{ animationDelay: "1.1s" }}
            >
              1.7M
            </span>
          </div>
          <div className="relative mt-2 h-5 text-[13px] tabular-nums text-muted" aria-hidden="true">
            <span className="absolute left-0">2000</span>
            <span className="absolute -translate-x-1/2" style={{ left: tickLeft(10) }}>2010</span>
            <span className="absolute -translate-x-1/2" style={{ left: tickLeft(20) }}>2020</span>
            <span className="absolute right-0">2025</span>
          </div>
          <figcaption className="mt-4 text-[13px] text-muted">
            Papers added to PubMed per year, before preprints. Source:{" "}
            <a href={SOURCE_URL} className="underline underline-offset-2 hover:text-fg">
              PubMed
            </a>
            , counted October 2026.
          </figcaption>
          <table className="sr-only">
            <caption>Papers added to PubMed per year</caption>
            <thead>
              <tr>
                <th scope="col">Year</th>
                <th scope="col">Papers added</th>
              </tr>
            </thead>
            <tbody>
              {ADDED.map(([year, n]) => (
                <tr key={year}>
                  <td>{year}</td>
                  <td>{fmt(n)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </figure>
      </Container>
    </section>
  );
}
