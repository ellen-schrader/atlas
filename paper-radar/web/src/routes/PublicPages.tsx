import { type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Container, ISSUES_URL, PublicFooter, PublicHeader, REPO_URL } from "@/components/landing/PublicChrome";

/** About, Privacy and Terms. Open signed in and signed out (both route trees in
 *  App.tsx), so a member can read the terms they agreed to. The text is
 *  docs/LEGAL_PAGES_DRAFT.md; change both together, and update the provider
 *  table here whenever Atlas starts sending data somewhere new. */

const CONTACT = "hello@labatlas.app";
const UPDATED = "18 October 2026";  // bump when the text changes

function PublicPage({ title, signedIn, children }: { title: string; signedIn: boolean; children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-col bg-bg text-fg">
      <PublicHeader signedIn={signedIn} />
      <main className="flex-1">
        <Container className="py-16 sm:py-20">
          <article className="max-w-[44rem]">
            <h1 className="text-4xl font-bold leading-tight tracking-[-0.03em]">{title}</h1>
            <div className="mt-8 flex flex-col gap-4 text-[17px] leading-relaxed text-fg">{children}</div>
          </article>
        </Container>
      </main>
      <PublicFooter />
    </div>
  );
}

function H2({ children }: { children: ReactNode }) {
  return <h2 className="mt-6 text-xl font-bold tracking-[-0.015em]">{children}</h2>;
}

function Updated() {
  return <p className="text-sm text-muted">Last updated {UPDATED}</p>;
}

function Bullets({ children }: { children: ReactNode }) {
  return <ul className="flex list-disc flex-col gap-2 pl-6 marker:text-muted">{children}</ul>;
}

function Mail() {
  return (
    <a href={`mailto:${CONTACT}`} className="text-accent underline underline-offset-2">
      {CONTACT}
    </a>
  );
}

function A({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} className="text-accent underline underline-offset-2">
      {children}
    </a>
  );
}

export function About({ signedIn = false }: { signedIn?: boolean }) {
  return (
    <PublicPage title="About Atlas" signedIn={signedIn}>
      <p>
        Atlas is a shared paper library for research groups. Everyone in a lab adds the papers they read;
        Atlas fills in the metadata, merges duplicates and preprints, and keeps the lab’s notes and
        discussion with each paper. Connected to Claude, it lets Claude answer from the papers a lab chose
        to keep.
      </p>
      <p>
        Atlas is built by Ellen Schrader, a PhD student, as an independent, non-commercial project. It
        started as the reading library for the lab Ellen works in. It is not a product of, or endorsed by,
        any university, institute or funder.
      </p>
      <p>
        Atlas is in beta. Things will change and sometimes break. The code is public under the MIT licence
        at <A href={REPO_URL}>github.com/ellen-schrader/atlas</A>, and bug reports and ideas are welcome as{" "}
        <A href={ISSUES_URL}>GitHub issues</A>.
      </p>
      <p>
        Contact: <Mail />
      </p>
    </PublicPage>
  );
}

const PROVIDERS: [string, string, string, string][] = [
  ["Supabase", "Database, sign-in, file storage", "Everything above", "EU (Ireland)"],
  ["Fly.io", "Runs the Atlas server", "Requests as they pass through", "UK (London)"],
  ["Vercel", "Serves the website", "Page requests, IP address", "Global network"],
  ["Resend", "Sends sign-in and password emails", "Your email address", "EU (Ireland)"],
  ["Voyage AI", "Turns paper text and search queries into embeddings for semantic search", "Paper titles and abstracts, search text", "USA"],
  ["Anthropic", "Generates tags and topic summaries", "Paper titles and abstracts", "USA"],
  ["Crossref, OpenAlex, arXiv, bioRxiv, doi.org", "Look up paper metadata", "The DOI or link you added", "Various"],
  ["Microsoft Teams", "Only if your lab connects a Teams channel", "Paper cards posted to that channel; messages posted to Atlas from it", "Microsoft"],
];

export function Privacy({ signedIn = false }: { signedIn?: boolean }) {
  return (
    <PublicPage title="Privacy" signedIn={signedIn}>
      <Updated />
      <p>
        This page explains what Atlas stores about you, why, where, and who else sees it. Atlas is run by
        Ellen Schrader as an individual (“I” below), who is the data controller. Contact: <Mail />.
      </p>

      <H2>What Atlas stores</H2>
      <Bullets>
        <li>
          <strong>Your account:</strong> email address, display name and a password managed by the
          authentication service. Atlas never sees your password in plain text.
        </li>
        <li>
          <strong>Your labs:</strong> which labs you belong to and your role in them.
        </li>
        <li>
          <strong>What you add and do:</strong> papers you post, and the notes, tags, comments and
          reactions you write; your bookmarks and reading lists; which papers you have opened; figures you
          upload.
        </li>
        <li>
          <strong>Claude activity:</strong> if your lab turns on Claude access, a log of each request
          Claude makes through Atlas (who, which tool, when and whether it succeeded). Your lab can see this
          log.
        </li>
        <li>
          <strong>In your browser:</strong> your sign-in session, your theme choice and which of your labs
          is open, stored in local storage. Atlas uses no advertising or analytics cookies and no tracking.
        </li>
      </Bullets>

      <H2>Why</H2>
      <p>
        Only to run the service: to show your lab its library, keep it tidy, recommend papers from your own
        reading, and answer Claude’s requests when your lab allows it. The legal basis is legitimate
        interest in providing a service you signed up for. Nothing is sold, and nothing is used for
        advertising.
      </p>

      <H2>Who can see it</H2>
      <Bullets>
        <li>
          <strong>Your lab:</strong> members of a lab see that lab’s papers, notes, comments and reactions,
          and who posted them. Other labs cannot.
        </li>
        <li>
          <strong>Me:</strong> as the person running Atlas, I can access the database to fix problems. I do
          not browse it otherwise.
        </li>
      </Bullets>

      <H2>Where it is stored, and the services Atlas uses</H2>
      <div className="overflow-x-auto rounded-card border border-border">
        <table className="w-full min-w-[40rem] border-collapse text-left text-[15px]">
          <thead className="bg-surface-2 text-sm">
            <tr>
              <th scope="col" className="px-4 py-3 font-semibold">Service</th>
              <th scope="col" className="px-4 py-3 font-semibold">What it does for Atlas</th>
              <th scope="col" className="px-4 py-3 font-semibold">What it receives</th>
              <th scope="col" className="px-4 py-3 font-semibold">Location</th>
            </tr>
          </thead>
          <tbody>
            {PROVIDERS.map(([name, does, gets, where]) => (
              <tr key={name} className="border-t border-border align-top">
                <th scope="row" className="px-4 py-3 font-semibold">{name}</th>
                <td className="px-4 py-3 text-muted">{does}</td>
                <td className="px-4 py-3 text-muted">{gets}</td>
                <td className="px-4 py-3 text-muted">{where}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        Paper text sent to Voyage AI and Anthropic is about the paper, not about you. Your notes and
        comments are not sent to either for these features.
      </p>
      <p>
        <strong>When you use Claude with Atlas,</strong> Claude receives the results of your requests:
        paper details, tags and lab notes. That happens under your own Claude account and Anthropic’s terms
        for it, not through Atlas’s own Anthropic account.
      </p>
      <p>Where data leaves the UK or EU, these providers use standard contractual safeguards.</p>

      <H2>How long</H2>
      <p>
        For as long as your account exists. You can delete your account yourself in Settings, and your
        account details are removed at once. What you posted to a lab (papers, comments, figures, shared
        maps) stays with that lab without your name, unless you ask <Mail /> for it to be removed too. A lab you are the only member of is deleted with your account.
      </p>

      <H2>Your rights</H2>
      <p>
        You can ask for a copy of your data, a correction, deletion, or an objection to how it is used, by
        emailing <Mail />. I’ll reply within 30 days. If you are unhappy with the answer, you can complain
        to the UK Information Commissioner’s Office (<A href="https://ico.org.uk">ico.org.uk</A>).
      </p>

      <H2>Children</H2>
      <p>Atlas is for researchers and is not intended for anyone under 18.</p>

      <H2>Changes</H2>
      <p>If this page changes in a way that matters, I’ll say so in the app.</p>
    </PublicPage>
  );
}

export function Terms({ signedIn = false }: { signedIn?: boolean }) {
  return (
    <PublicPage title="Terms" signedIn={signedIn}>
      <Updated />
      <p>These terms apply when you use Atlas. By creating an account you agree to them.</p>
      <ol className="flex list-decimal flex-col gap-3 pl-6 marker:font-semibold marker:text-muted">
        <li>
          <strong>What Atlas is.</strong> A free, non-commercial beta run by an individual in spare time.
          Features may change, break or be removed, and the service may pause or end. If it ends, I will
          give notice where I can and a way to export your papers.
        </li>
        <li>
          <strong>No warranty.</strong> Atlas is provided “as is”, without warranties of any kind. Metadata,
          merges, tags, summaries and anything Claude says using Atlas can be wrong. Check sources before
          relying on them, especially in published work.
        </li>
        <li>
          <strong>Liability.</strong> To the extent the law allows, I am not liable for losses from using or
          being unable to use Atlas, including lost data. Keep your own copies of anything important; Atlas
          can export to BibTeX, RIS, CSV and Markdown. Nothing here limits liability that cannot be limited
          by law.
        </li>
        <li>
          <strong>Your content.</strong> You keep ownership of what you add: notes, comments and uploaded
          figures. You give Atlas permission to store and show it to your lab, and to process it as
          described on the <Link to="/privacy" className="text-accent underline underline-offset-2">Privacy</Link>{" "}
          page. Only upload what you have the right to share, for example no copyrighted PDFs or figures you
          may not reuse.
        </li>
        <li>
          <strong>Acceptable use.</strong> Don’t use Atlas to break the law, to harass anyone, to get at
          another lab’s data, or to overload or probe the service. Accounts that do may be suspended.
        </li>
        <li>
          <strong>Labs.</strong> Lab owners control membership and Claude access for their lab. Members
          agree that what they post is visible to their lab.
        </li>
        <li>
          <strong>Claude.</strong> Connecting Claude is optional, and your use of Claude is governed by your
          agreement with Anthropic. Atlas is not affiliated with or endorsed by Anthropic.
        </li>
        <li>
          <strong>Law.</strong> These terms are governed by the law of England and Wales.
        </li>
        <li>
          <strong>Contact.</strong> <Mail />
        </li>
      </ol>
    </PublicPage>
  );
}
