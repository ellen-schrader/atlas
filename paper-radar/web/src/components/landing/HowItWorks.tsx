import { type ReactNode } from "react";
import { Check } from "lucide-react";

import { Container } from "@/components/landing/PublicChrome";

function Step({ title, body, children }: { title: string; body: string; children: ReactNode }) {
  return (
    <article className="flex flex-col gap-5">
      <div
        className="flex min-h-[196px] flex-col gap-2 rounded-card border border-border bg-surface p-4 text-[13px]"
        aria-hidden="true"
      >
        {children}
      </div>
      <div>
        <h3 className="text-xl font-bold tracking-[-0.015em]">{title}</h3>
        <p className="mt-2 text-[17px] leading-relaxed text-muted">{body}</p>
      </div>
    </article>
  );
}

function Row({ left, right, className = "bg-surface-2" }: { left: ReactNode; right: ReactNode; className?: string }) {
  return (
    <span className={`flex items-center justify-between gap-2 rounded-control px-3 py-2.5 ${className}`}>
      <span className="min-w-0 truncate">{left}</span>
      <span className="shrink-0 text-muted">{right}</span>
    </span>
  );
}

export function HowItWorks() {
  return (
    <Container className="py-20 sm:py-24">
      <h2 className="text-3xl font-bold leading-[1.08] tracking-[-0.03em] sm:text-[2.75rem]">How it works</h2>
      <div className="mt-10 grid gap-x-6 gap-y-10 md:grid-cols-3">
        <Step title="Add papers" body="However your lab already shares them.">
          <Row left="10.1038/s41587-026-03004-8" right="DOI" />
          <Row left="my-library.bib" right="BibTeX" />
          <Row left="Posted in the lab channel" right="Teams" />
        </Step>
        <Step title="Atlas tidies up" body="Metadata filled in, duplicates and preprints merged.">
          <Row left="bioRxiv preprint" right="2025" className="border border-dashed border-border-strong text-muted" />
          <Row left="Journal version" right="2026" className="border border-dashed border-border-strong text-muted" />
          <Row
            left={<span className="font-semibold">One record, both versions linked</span>}
            right={<Check size={16} strokeWidth={2.5} className="text-accent" />}
            className="border border-accent"
          />
        </Step>
        <Step title="Connect Claude" body="Add Atlas once. The lab owner switches access on.">
          <span className="text-muted">Claude › Settings › Connectors</span>
          <Row
            left={<span className="font-semibold">Atlas</span>}
            right={
              <span className="inline-flex items-center gap-1.5">
                <span className="h-[7px] w-[7px] rounded-full bg-success" />
                Connected
              </span>
            }
          />
          <span className="text-muted">Atlas › Lab settings</span>
          <Row
            left={<span className="font-semibold">Claude access</span>}
            right={
              <span className="flex h-5 w-[34px] items-center justify-end rounded-full bg-accent p-0.5">
                <span className="h-4 w-4 rounded-full bg-white" />
              </span>
            }
          />
        </Step>
      </div>
    </Container>
  );
}
