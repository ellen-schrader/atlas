
import { AboutStrip, Close, LabControls } from "@/components/landing/Closing";
import { FindAgain } from "@/components/landing/FindAgain";
import { Hero } from "@/components/landing/Hero";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { PublicFooter, PublicHeader } from "@/components/landing/PublicChrome";
import { PubMedChart } from "@/components/landing/PubMedChart";
import { SameQuestion } from "@/components/landing/SameQuestion";
import { DEFAULT_TITLE, useDocumentTitle } from "@/hooks/useDocumentTitle";

/**
 * The public landing page (docs/LANDING_PAGE_PLAN.md, design G). It says what
 * Atlas is in one sentence, then shows rather than tells: the growth of PubMed,
 * search by meaning on a real library, the same question put to Claude with and
 * without that library, how it works, what the lab controls, and who makes it.
 * Every paper on it is real; the lab they come from is never named.
 */
export default function Landing() {
  useDocumentTitle(DEFAULT_TITLE, { raw: true });
  return (
    <div className="min-h-full bg-bg text-fg">
      <PublicHeader />
      <main>
        <Hero />
        <PubMedChart />
        <FindAgain />
        <SameQuestion />
        <HowItWorks />
        <LabControls />
        <AboutStrip />
        <Close />
      </main>
      <PublicFooter />
    </div>
  );
}
