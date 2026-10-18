import { Link } from "react-router-dom";
import { Check } from "lucide-react";

import { Container, GitHubMark, REPO_URL, SignupLink } from "@/components/landing/PublicChrome";

// "Read-only connector": the hosted server registers READ_TOOLS only
// (atlas_mcp/http.py). "Data stored in Europe": the database is; Voyage and
// Anthropic still see paper text in the US (see /privacy).
const CONTROLS = ["Off until you turn it on", "Read-only connector", "Every request logged", "Data stored in Europe"];

/** What the lab controls. Said as "your lab", not "the PI": whoever signs up
 *  first is often not the PI. */
export function LabControls() {
  return (
    <section className="border-y border-border bg-surface">
      <Container className="py-16 sm:py-20">
        <h2 className="text-2xl font-bold leading-tight tracking-[-0.03em] sm:text-4xl">
          Your lab decides what Claude can see.
        </h2>
        <ul className="mt-8 grid gap-x-8 gap-y-4 text-[17px] sm:grid-cols-2 lg:grid-cols-4">
          {CONTROLS.map((c) => (
            <li key={c} className="flex items-center gap-2.5">
              <Check size={18} strokeWidth={2.5} className="shrink-0 text-accent" aria-hidden="true" />
              {c}
            </li>
          ))}
        </ul>
      </Container>
    </section>
  );
}

export function AboutStrip() {
  return (
    <Container className="flex flex-wrap items-center justify-between gap-x-10 gap-y-4 pt-16">
      <p className="max-w-[38em] text-lg leading-relaxed">
        Atlas is built by Ellen Schrader, a PhD student. It started as the paper library of the lab
        Ellen works in, and is open source and in beta.
      </p>
      <a
        href={REPO_URL}
        className="inline-flex items-center gap-2 font-semibold text-accent transition hover:brightness-110"
      >
        <GitHubMark size={18} />
        Code and issues on GitHub
      </a>
    </Container>
  );
}

export function Close() {
  return (
    <Container className="py-24 text-center sm:py-28">
      <h2 className="text-balance text-4xl font-bold leading-[1.06] tracking-[-0.035em] sm:text-5xl">
        Start with the papers you have.
      </h2>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-3">
        <SignupLink />
        <Link to="/login" className="font-semibold text-muted transition hover:text-fg">
          Sign in
        </Link>
      </div>
    </Container>
  );
}
