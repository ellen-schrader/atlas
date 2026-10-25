import { type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Brand } from "@/components/Brand";
import { ThemeToggle } from "@/components/ThemeToggle";

export const REPO_URL = "https://github.com/ellen-schrader/atlas";
export const ISSUES_URL = `${REPO_URL}/issues`;

/** The product in one sentence, shared by the landing hero and the sign-up panel
 *  (index.html's og tags carry the same words for link previews). */
export const HEADLINE = "Your lab’s papers, in one place. Ready for Claude.";
export const TAGLINE = "Add papers however your lab shares them. Claude answers from them, with citations.";

/** The page width every public section shares. */
export function Container({ className = "", children }: { className?: string; children: ReactNode }) {
  return <div className={`mx-auto max-w-6xl px-6 ${className}`}>{children}</div>;
}

/** Primary call to action: one per screen, repeated down the landing page. */
export function SignupLink({ small = false }: { small?: boolean }) {
  return (
    <Link
      to="/login?mode=signup"
      className={`inline-flex items-center rounded-control bg-accent font-semibold text-accent-fg transition hover:brightness-110 ${small ? "px-4 py-2.5 text-sm" : "px-5 py-3 text-base"}`}
    >
      Create your lab
    </Link>
  );
}

/** The GitHub mark, for links to the repository. */
export function GitHubMark({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

/** Header for the signed-out pages. `signedIn` swaps the sign-up actions for a
 *  way back into the app, since About/Privacy/Terms are open to members too. */
export function PublicHeader({ signedIn = false }: { signedIn?: boolean }) {
  return (
    <header className="border-b border-border">
      <Container className="flex flex-wrap items-center justify-between gap-4 py-4">
        <Link to="/" className="flex items-center gap-2.5" aria-label="Atlas home">
          <Brand size={24} />
          <span className="rounded-chip border border-accent px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-accent">
            Beta
          </span>
        </Link>
        <nav className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm font-medium">
          <ThemeToggle />
          {signedIn ? (
            <Link to="/" className="text-muted transition hover:text-fg">
              Back to Atlas
            </Link>
          ) : (
            <>
              <Link to="/login" className="text-muted transition hover:text-fg">
                Sign in
              </Link>
              <SignupLink small />
            </>
          )}
        </nav>
      </Container>
    </header>
  );
}

export function PublicFooter() {
  return (
    <footer className="border-t border-border">
      <Container className="flex flex-wrap items-center justify-between gap-4 py-6 text-sm text-muted">
        <span>Atlas is in beta and provided as is.</span>
        <nav className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <Link to="/about" className="transition hover:text-fg">
            About
          </Link>
          <Link to="/privacy" className="transition hover:text-fg">
            Privacy
          </Link>
          <Link to="/terms" className="transition hover:text-fg">
            Terms
          </Link>
          <a href={ISSUES_URL} className="inline-flex items-center gap-1.5 transition hover:text-fg">
            <GitHubMark size={14} />
            Report an issue
          </a>
        </nav>
      </Container>
    </footer>
  );
}
