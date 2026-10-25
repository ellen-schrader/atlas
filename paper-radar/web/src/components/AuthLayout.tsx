import { type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Brand } from "@/components/Brand";
import { HEADLINE, TAGLINE } from "@/components/landing/PublicChrome";
import { ThemeToggle } from "@/components/ThemeToggle";

/** Split-screen shell for the signed-out screens: the product in one sentence
 *  on the left (the landing page's words, on its imaging ground), the form on
 *  the right. Collapses to just the form, with a compact brand, below md.
 *  `tagline` only on sign-up: returning users don't need the pitch twice.
 *  `homeLink={false}` for ResetPassword: App renders it from state, not the
 *  route, so a link home would change the URL, drop the reset token, and leave
 *  the form on screen. */
export function AuthLayout({
  children,
  homeLink = true,
  tagline = false,
}: {
  children: ReactNode;
  homeLink?: boolean;
  tagline?: boolean;
}) {
  const brand = (size: number, className: string) =>
    homeLink ? (
      <Link to="/" aria-label="Atlas home" className={className}>
        <Brand size={size} />
      </Link>
    ) : (
      <div className={className}>
        <Brand size={size} />
      </div>
    );
  return (
    <div className="flex min-h-full">
      {/* `dark` scopes the dark tokens, so the panel is the imaging ground in both themes. */}
      <div className="dark hidden w-[44%] max-w-xl shrink-0 border-r border-border bg-surface text-fg md:block">
        <div className="flex h-full flex-col justify-between p-10">
          {brand(28, "w-fit")}
          <div className="max-w-sm">
            <h1 className="text-balance text-3xl font-bold leading-tight tracking-tight">
              {HEADLINE}
            </h1>
            {tagline && <p className="mt-4 text-sm leading-relaxed text-muted">{TAGLINE}</p>}
          </div>
        </div>
      </div>

      <div className="relative flex flex-1 items-center justify-center p-6">
        <div className="absolute right-4 top-4">
          <ThemeToggle />
        </div>
        <div className="w-full max-w-sm">
          {brand(24, "mb-6 block w-fit md:hidden")}
          {children}
        </div>
      </div>
    </div>
  );
}
