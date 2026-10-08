import type { Session } from "@supabase/supabase-js";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useOutletContext } from "react-router-dom";
import { Menu } from "lucide-react";

import { AtlasMark } from "@/components/Brand";
import { FigureModalProvider } from "@/components/FigureModal";
import { NotificationsBell } from "@/components/NotificationsBell";
import { PaperModalProvider } from "@/components/PaperModal";
import { CollapsedBar, Sidebar } from "@/components/sidebar/Sidebar";
import { FOCUS_RING } from "@/components/sidebar/nav";
import { ToastProvider } from "@/components/Toast";
import { useElementWidth } from "@/hooks/useElementWidth";
import { useProfile } from "@/hooks/useProfile";
import type { Team } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface AppContext {
  session: Session;
  team: Team;
  userId: string;
  displayName: string;
  /** Width of the whole app shell (nav included) — Home's breakpoints key off it. */
  shellWidth: number;
}

export function useAppContext() {
  return useOutletContext<AppContext>();
}

/** Nav presentation, from the width of the app shell (not a media query: the
 *  same breakpoints have to hold wherever the shell is embedded).
 *  full   ≥ 1360px — labelled sidebar
 *  rail   640–1359 — 68px icon bar, so a 1280px laptop keeps its content width
 *  mobile < 640    — top bar + drawer */
export type NavMode = "full" | "rail" | "mobile";

export function navModeFor(shellWidth: number): NavMode {
  if (shellWidth >= 1360) return "full";
  if (shellWidth >= 640) return "rail";
  return "mobile";
}

export default function Layout({
  session,
  team,
  labs,
  onSwitchLab,
}: {
  session: Session;
  team: Team;
  labs: Team[];
  onSwitchLab: (teamId: string) => boolean;
}) {
  const { data: profile } = useProfile(session.user.id);
  const displayName = profile?.display_name ?? session.user.email ?? "You";
  const shellRef = useRef<HTMLDivElement>(null);
  // Before the first measurement the shell is the viewport; reading it avoids a
  // flash of the mobile nav on a desktop load.
  const shellWidth = useElementWidth(shellRef) || window.innerWidth;
  const mode = navModeFor(shellWidth);
  const ctx: AppContext = { session, team, userId: session.user.id, displayName, shellWidth };
  const sidebar = {
    userId: session.user.id,
    email: session.user.email ?? "",
    displayName,
    team,
    labs,
    onSwitchLab,
  };

  return (
    <div
      ref={shellRef}
      className={cn(
        "flex min-h-screen",
        mode === "mobile" ? "flex-col" : "h-screen flex-row overflow-hidden",
      )}
    >
      {/* The shell is the viewport and only <main> scrolls, so the nav stays in
          view on a long page without needing to be sticky itself. */}
      {mode === "full" && (
        <aside className="flex h-full w-[232px] shrink-0 flex-col gap-5 overflow-y-auto border-r border-border bg-surface p-4">
          <Sidebar {...sidebar} />
        </aside>
      )}
      {mode === "rail" && <CollapsedBar {...sidebar} />}
      {mode === "mobile" && <MobileNav {...sidebar} />}

      <main className="min-w-0 flex-1 overflow-auto">
        <ToastProvider>
          <PaperModalProvider teamId={team.id} teamName={team.name} userId={session.user.id}>
            <FigureModalProvider teamId={team.id} userId={session.user.id}>
              <Outlet context={ctx} />
            </FigureModalProvider>
          </PaperModalProvider>
        </ToastProvider>
      </main>
    </div>
  );
}

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Phone: a top bar whose menu button opens the full sidebar as a drawer. The
 *  drawer is a modal — focus is trapped in it, and comes back to the menu
 *  button however it closes (scrim, Escape, or following a link). */
function MobileNav(p: Parameters<typeof Sidebar>[0]) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  // Close on a press *and* release on the scrim, as ui/modal does — not on
  // `click`. An open popover inside the drawer (useDismissable) swallows the
  // pointerdown, so that tap closes the popover alone; a click would still
  // arrive here and take the drawer down with it.
  const pressedScrim = useRef(false);
  const { pathname } = useLocation();

  const close = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };

  // Any navigation closes it — including ones that don't go through a nav row.
  const lastPath = useRef(pathname);
  useEffect(() => {
    if (pathname === lastPath.current) return;
    lastPath.current = pathname;
    if (open) close();
  }, [pathname]);

  useEffect(() => {
    if (open) drawerRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
  }, [open]);

  // React's handler, not a document listener: a popover inside the drawer (the
  // profile menu, the bell) takes Escape in the capture phase first, so one
  // press closes the innermost layer only.
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key !== "Tab") return;
    const items = Array.from(drawerRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <>
      <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
        <button
          ref={buttonRef}
          type="button"
          aria-label="Menu"
          aria-expanded={open}
          aria-controls="mobile-nav"
          onClick={() => setOpen(true)}
          className={cn(
            "-ml-2 grid h-11 w-11 place-items-center rounded-control text-muted transition hover:bg-surface-2 hover:text-fg",
            FOCUS_RING,
          )}
        >
          <Menu size={18} />
        </button>
        <span className="flex items-center gap-2 font-serif text-lg font-semibold tracking-tight">
          <AtlasMark size={21} className="text-accent" /> Atlas
        </span>
        <NotificationsBell userId={p.userId} align="right" className="ml-auto" />
      </header>

      {/* Mounted only while open, and never transformed: the profile menu inside
          is position: fixed, which a transformed ancestor would re-anchor. */}
      {open && (
        <>
          <div
            className="fixed inset-0 z-30 bg-[rgba(4,6,10,.6)]"
            onPointerDown={(e) => {
              pressedScrim.current = e.target === e.currentTarget;
            }}
            onPointerUp={(e) => {
              if (e.target === e.currentTarget && pressedScrim.current) close();
              pressedScrim.current = false;
            }}
            aria-hidden
          />
          <aside
            id="mobile-nav"
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Menu"
            onKeyDown={onKeyDown}
            className="fixed inset-y-0 left-0 z-40 flex w-[280px] max-w-[85vw] flex-col gap-5 overflow-y-auto border-r border-border bg-surface p-4"
          >
            <Sidebar {...p} drawer onNavigate={close} />
          </aside>
        </>
      )}
    </>
  );
}
