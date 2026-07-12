import { type ReactNode } from "react";
import { Compass } from "lucide-react";

import { Cover } from "@/components/Cover";
import { ThemeToggle } from "@/components/ThemeToggle";

/** Split-screen shell for the signed-out screens: a branded panel with the
 *  app's microscopy motif on the left, the form on the right. Collapses to just
 *  the form (with a compact brand) below md. */
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full">
      <div className="relative hidden w-[44%] max-w-xl shrink-0 overflow-hidden border-r border-border bg-surface md:block">
        <Cover seed="atlas-brand" className="absolute inset-0 h-full w-full opacity-25" />
        <div className="relative flex h-full flex-col justify-between p-10">
          <div className="flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-accent text-white">
              <Compass size={20} />
            </span>
            <span className="text-lg font-semibold tracking-tight">Atlas</span>
          </div>
          <div className="max-w-sm">
            <h1 className="text-balance text-3xl font-bold leading-tight tracking-tight">
              Your lab’s paper firehose, turned into a shared radar.
            </h1>
            <p className="mt-4 text-sm leading-relaxed text-muted">
              Post papers, discuss them with your team, and never lose the one someone shared last
              month.
            </p>
          </div>
        </div>
      </div>

      <div className="relative flex flex-1 items-center justify-center p-6">
        <div className="absolute right-4 top-4">
          <ThemeToggle />
        </div>
        <div className="w-full max-w-sm">{children}</div>
      </div>
    </div>
  );
}
