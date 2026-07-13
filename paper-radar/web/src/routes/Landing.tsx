import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ImageIcon, LibraryBig, Sparkles } from "lucide-react";

import { AtlasMark } from "@/components/Brand";
import { HeroField } from "@/components/HeroField";
import { ThemeToggle } from "@/components/ThemeToggle";

/**
 * The public landing page — the app's first public surface. Until now every
 * signed-out route redirected to /login, so there was nothing to send anyone.
 *
 * Copy follows the approved positioning (Territory 2): a lab's real asset is its
 * taste and its visual style, and Atlas is the first thing that writes them down and
 * hands them to Claude. Structure: lead with the claim, immediately answer the
 * cold-start objection with the mechanism ("it learns by being used"), then the two
 * readers, then close on what a lab actually loses today.
 */
export default function Landing() {
  return (
    <div className="min-h-screen bg-bg">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <span className="flex items-center gap-2 font-serif text-xl font-semibold tracking-tight text-fg">
          <AtlasMark size={26} className="text-accent" />
          Atlas
        </span>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <Link
            to="/login"
            className="rounded-control px-3 py-1.5 text-sm font-medium text-muted transition hover:text-fg"
          >
            Sign in
          </Link>
        </div>
      </header>

      {/* ── hero: the product's argument, before a word of copy ── */}
      <section className="relative isolate overflow-hidden border-b border-border">
        <HeroField className="absolute inset-0 h-full w-full" />
        {/* Two overlays, so the field reads as a ring around the type rather than
            noise behind it: one clears the centre where the words are, the other
            fades the edges into the page so the field has no hard cut-off. Without
            the first, body copy sits on top of scattered points and gets hard to
            read — worst in light theme, where the dots and the muted text are close
            in value. */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse 52% 42% at 50% 44%, var(--bg) 30%, transparent 78%)",
          }}
          aria-hidden
        />
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse at 50% 45%, transparent 35%, var(--bg) 88%)",
          }}
          aria-hidden
        />
        <div className="relative mx-auto max-w-3xl px-6 py-28 text-center sm:py-36">
          <h1 className="text-balance font-serif text-4xl font-semibold leading-[1.05] tracking-tight text-fg sm:text-6xl">
            Every lab has a taste.{" "}
            <em className="not-italic text-accent">Atlas gives yours to Claude.</em>
          </h1>
          <p className="mx-auto mt-6 max-w-xl text-balance text-base leading-relaxed text-muted sm:text-lg">
            The papers you save, the figures you admire, the ones you argue about — Atlas learns your
            lab’s judgment from how you already work, then hands it to Claude Code and Claude for
            Life Sciences.
          </p>

          <div className="mt-9 flex flex-wrap justify-center gap-3">
            <Link
              to="/login"
              className="inline-flex items-center gap-2 rounded-control bg-accent px-5 py-2.5 text-sm font-semibold text-accent-fg transition hover:brightness-110"
            >
              Create your lab <ArrowRight size={16} />
            </Link>
            <a
              href="#learns"
              className="inline-flex items-center gap-2 rounded-control border border-border-strong px-5 py-2.5 text-sm font-semibold text-fg transition hover:border-accent hover:text-accent"
            >
              How it learns
            </a>
          </div>

          <p className="mt-8 font-mono text-xs text-faint">
            Your papers stay in your lab · Claude’s access is owner-controlled and logged
          </p>
        </div>
      </section>

      {/* ── the mechanism: answers cold start before it's an objection ── */}
      <Section id="learns" eyebrow="How it works" title="It learns by being used.">
        <p className="max-w-[64ch] text-muted">
          There’s no profile to fill in and no model to tune. Atlas watches how your lab{" "}
          <strong className="font-semibold text-fg">already works</strong> — and weights what it
          sees, because <strong className="font-semibold text-fg">not all engagement is
          endorsement</strong>.
        </p>

        <div className="mt-7 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Lesson channel="ch-2" action="You save a paper" means="The strongest signal there is." weight="1.5×" />
          <Lesson channel="ch-1" action="You react to it" means="Endorsement." weight="1.0×" />
          <Lesson channel="ch-5" action="You argue in the comments" means="Engagement." weight="0.75×" />
          <Lesson channel="ch-3" action="You react 🤔" means="Sceptical, not keen." weight="0.3×" />
          <Lesson channel="ch-off" action="You merely read it" means="Consumed ≠ liked." weight="0.25×" />
          <Lesson channel="ch-6" action="You add a figure" means="Teaches the palette, not the taste." />
        </div>

        <p className="mt-6 max-w-[70ch] text-sm text-muted">
          Recent interest outweighs old — every signal halves in weight each quarter, so the model
          tracks <strong className="font-semibold text-fg">where the lab is going</strong>, not where
          it’s been. Day one it’s a shared library. By month three it knows what your lab will care
          about.
        </p>
      </Section>

      {/* ── two readers ── */}
      <Section eyebrow="The navigation system" title="Atlas has two readers: your lab, and Claude." alt>
        <p className="max-w-[64ch] text-muted">
          A lab’s real asset isn’t its folder of PDFs. It’s{" "}
          <strong className="font-semibold text-fg">what the lab thinks is worth reading</strong> and{" "}
          <strong className="font-semibold text-fg">what its figures look like</strong>. Atlas
          computes both — then serves them over MCP, so Claude searches your corpus, cites your
          papers, and plots in your lab’s palette instead of the field’s generic average.
        </p>

        <div className="mt-7 grid gap-4 md:grid-cols-3">
          <Surface
            icon={<LibraryBig size={17} />}
            title="Papers"
            body="Everything your lab has shared, deduplicated and enriched with real metadata. Full-text and semantic search, an interactive map of the corpus, and the stats behind it."
          />
          <Surface
            icon={<ImageIcon size={17} />}
            title="Your lab’s look"
            body="The figures your lab admires. Atlas derives your palette from them — and a real matplotlib style sheet, so a figure Claude makes in your repo already looks like it belongs in your paper."
          />
          <Surface
            icon={<Sparkles size={17} />}
            title="Connect Claude"
            body="One config file. Access is a lab-wide setting an owner controls, it's read-only apart from posting a paper you confirm, and every call is logged where the whole lab can see it."
          />
        </div>
      </Section>

      {/* ── the close ── */}
      <section className="border-t border-border">
        <div className="mx-auto max-w-6xl px-6 py-20 sm:py-28">
          <h2 className="max-w-[18ch] text-balance font-serif text-3xl font-semibold leading-tight tracking-tight text-fg sm:text-5xl">
            When the postdoc leaves,{" "}
            <em className="not-italic text-accent">the taste stays.</em>
          </h2>
          <p className="mt-5 max-w-[58ch] text-muted">
            Five years of judgment about what’s worth reading walks out of your lab with every person
            who finishes. Atlas keeps it — the papers, the arguments, the figures you admired — so the
            next person inherits{" "}
            <strong className="font-semibold text-fg">the lab’s mind, not just its Dropbox</strong>.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              to="/login"
              className="inline-flex items-center gap-2 rounded-control bg-accent px-5 py-2.5 text-sm font-semibold text-accent-fg transition hover:brightness-110"
            >
              Create your lab <ArrowRight size={16} />
            </Link>
            <Link
              to="/login"
              className="inline-flex items-center gap-2 rounded-control border border-border-strong px-5 py-2.5 text-sm font-semibold text-fg transition hover:border-accent hover:text-accent"
            >
              Sign in
            </Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-6 font-mono text-xs text-faint">
          <span className="flex items-center gap-2">
            <AtlasMark size={15} className="text-accent" /> Atlas — a lab’s reading, mapped
          </span>
          <span>Built for research groups</span>
        </div>
      </footer>
    </div>
  );
}

function Section({
  id,
  eyebrow,
  title,
  children,
  alt,
}: {
  id?: string;
  eyebrow: string;
  title: string;
  children: ReactNode;
  alt?: boolean;
}) {
  return (
    <section id={id} className={alt ? "border-b border-border bg-surface" : "border-b border-border"}>
      <div className="mx-auto max-w-6xl px-6 py-20">
        <p className="font-mono text-xs uppercase tracking-[0.14em] text-accent">{eyebrow}</p>
        <h2 className="mt-3 max-w-[20ch] text-balance font-serif text-3xl font-semibold leading-tight tracking-tight text-fg sm:text-4xl">
          {title}
        </h2>
        <div className="mt-5">{children}</div>
      </div>
    </section>
  );
}

/** One engagement signal and what it teaches — the real weights from `_taste_vector`. */
function Lesson({
  channel,
  action,
  means,
  weight,
}: {
  channel: string;
  action: string;
  means: string;
  weight?: string;
}) {
  return (
    <div className="flex gap-3 rounded-card border border-border bg-bg p-3.5">
      {/* the channel stripe ties each signal to the map's colour language */}
      <span
        className="w-[3px] shrink-0 rounded-full"
        style={{ background: `var(--${channel})` }}
        aria-hidden
      />
      <div className="min-w-0">
        <div className="text-sm font-semibold text-fg">{action}</div>
        <div className="mt-0.5 text-xs text-muted">
          {means}
          {weight && <span className="ml-1.5 font-mono text-accent">{weight}</span>}
        </div>
      </div>
    </div>
  );
}

function Surface({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <article className="flex flex-col gap-2 rounded-card border border-border bg-bg p-5">
      <span className="grid h-9 w-9 place-items-center rounded-control bg-accent-weak text-accent">
        {icon}
      </span>
      <h3 className="mt-1 font-serif text-lg font-semibold tracking-tight text-fg">{title}</h3>
      <p className="text-sm leading-relaxed text-muted">{body}</p>
    </article>
  );
}
