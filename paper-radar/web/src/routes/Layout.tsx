import type { Session } from "@supabase/supabase-js";
import { useRef, useState } from "react";
import { NavLink, Outlet, useOutletContext } from "react-router-dom";
import {
  BookMarked,
  Images,
  LayoutGrid,
  LibraryBig,
  LogOut,
  Map as MapIcon,
  Menu,
  Settings as SettingsIcon,
  Sparkles,
  Users,
  X,
} from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { AtlasMark } from "@/components/Brand";
import { FigureModalProvider } from "@/components/FigureModal";
import { NotificationsBell } from "@/components/NotificationsBell";
import { PaperModalProvider } from "@/components/PaperModal";
import { ToastProvider } from "@/components/Toast";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { useDismissable } from "@/hooks/useDismissable";
import { useElementWidth } from "@/hooks/useElementWidth";
import { useProfile } from "@/hooks/useProfile";
import { supabase } from "@/lib/supabase";
import type { Team } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface AppContext {
  session: Session;
  team: Team;
  userId: string;
  displayName: string;
}

export function useAppContext() {
  return useOutletContext<AppContext>();
}

const NAV = [
  { to: "/", label: "Home", icon: LayoutGrid, end: true },
  { to: "/papers", label: "Papers", icon: LibraryBig, end: false },
  { to: "/reading", label: "Reading list", icon: BookMarked, end: false },
  { to: "/board", label: "Your lab’s look", icon: Images, end: false },
  { to: "/maps", label: "Maps", icon: MapIcon, end: false },
  { to: "/connect", label: "Connect Claude", icon: Sparkles, end: false },
];

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-3 rounded-control px-2.5 py-2 text-sm font-medium transition",
    isActive ? "bg-accent-weak text-accent" : "text-muted hover:bg-surface-2 hover:text-fg",
  );

function BrandMark({ size = 7 }: { size?: 6 | 7 }) {
  return <AtlasMark size={size === 7 ? 24 : 21} className="text-accent" />;
}

/** Nav presentation, from the width of the app shell (not a media query: the
 *  same breakpoints have to hold wherever the shell is embedded).
 *  full   ≥ 1360px — labelled sidebar
 *  rail   640–1359 — 64px icon strip, so a 1280px laptop keeps its content width
 *  mobile < 640    — top bar + drawer */
export type NavMode = "full" | "rail" | "mobile";

export function navModeFor(shellWidth: number): NavMode {
  if (shellWidth >= 1360) return "full";
  if (shellWidth >= 640) return "rail";
  return "mobile";
}

export default function Layout({ session, team }: { session: Session; team: Team }) {
  const { data: profile } = useProfile(session.user.id);
  const displayName = profile?.display_name ?? session.user.email ?? "You";
  const ctx: AppContext = { session, team, userId: session.user.id, displayName };
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  const shellRef = useRef<HTMLDivElement>(null);
  // Before the first measurement the shell is the viewport; reading it avoids a
  // flash of the mobile nav on a desktop load.
  const mode = navModeFor(useElementWidth(shellRef) || window.innerWidth);

  return (
    <div
      ref={shellRef}
      className={cn(
        "flex min-h-screen",
        mode === "mobile" ? "flex-col" : "h-screen flex-row overflow-hidden",
      )}
    >
      {mode === "mobile" && (
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
          <button
            aria-label="Open menu"
            onClick={() => setOpen(true)}
            className="grid h-11 w-11 place-items-center rounded-control text-muted transition hover:bg-surface-2 hover:text-fg"
          >
            <Menu size={18} />
          </button>
          <span className="flex items-center gap-2 font-serif text-lg font-semibold tracking-tight">
            <BrandMark size={6} /> Atlas
          </span>
          <NotificationsBell userId={session.user.id} align="right" className="ml-auto" />
        </header>
      )}

      {mode === "mobile" && open && (
        <div
          className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm"
          onClick={close}
          aria-hidden
        />
      )}

      {mode === "rail" ? (
        <IconRail userId={session.user.id} displayName={displayName} teamName={team.name} />
      ) : (
        <aside
          className={cn(
            "flex w-[232px] shrink-0 flex-col gap-5 border-r border-border bg-surface p-4",
            mode === "mobile"
              ? cn(
                  "fixed inset-y-0 left-0 z-40 transition-transform",
                  open ? "translate-x-0" : "-translate-x-full",
                )
              : "h-full",
          )}
        >
          <div className="flex items-center justify-between px-1">
            <span className="flex items-center gap-2 font-serif text-lg font-semibold tracking-tight">
              <BrandMark size={7} /> Atlas
            </span>
            <div className="flex items-center gap-1">
              {mode === "full" ? (
                <NotificationsBell userId={session.user.id} align="left" />
              ) : (
                <button
                  aria-label="Close menu"
                  onClick={close}
                  className="grid h-11 w-11 place-items-center rounded-control text-muted hover:bg-surface-2"
                >
                  <X size={16} />
                </button>
              )}
            </div>
          </div>

          <nav className="flex flex-col gap-0.5">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end} onClick={close} className={linkClass}>
                <Icon size={16} /> {label}
              </NavLink>
            ))}
          </nav>

          <div className="mt-auto flex flex-col gap-3 border-t border-border pt-4">
            <NavLink to="/settings" onClick={close} className={linkClass}>
              <SettingsIcon size={16} /> Settings
            </NavLink>

            <div className="flex items-center gap-2.5 rounded-control border border-border bg-surface-2 p-2.5">
              <Avatar name={displayName} size={32} />
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold">{displayName}</div>
                <div className="flex items-center gap-1 text-xs text-muted">
                  <Users size={12} /> {team.name}
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <ThemeToggle />
              <Button variant="ghost" size="sm" onClick={() => supabase.auth.signOut()}>
                <LogOut size={14} /> Log out
              </Button>
            </div>
          </div>
        </aside>
      )}

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

const railLinkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "grid h-11 w-11 place-items-center rounded-control transition",
    isActive ? "bg-accent-weak text-accent" : "text-muted hover:bg-surface-2 hover:text-fg",
  );

/** The 64px icon strip used between the phone and wide-desktop widths. Labels
 *  move into tooltips + aria-labels; the account controls (lab, theme, log out)
 *  move behind the avatar. */
function IconRail({
  userId,
  displayName,
  teamName,
}: {
  userId: string;
  displayName: string;
  teamName: string;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useDismissable(menuRef, menuOpen, () => setMenuOpen(false));

  return (
    <aside className="flex h-full w-16 shrink-0 flex-col items-center gap-4 border-r border-border bg-surface py-4">
      <span className="grid h-11 w-11 place-items-center" title="Atlas">
        <BrandMark size={7} />
      </span>
      {/* Near the top, not with the account controls: its dropdown opens downward. */}
      <NotificationsBell userId={userId} align="left" />

      <nav className="flex flex-col items-center gap-1">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} title={label} aria-label={label} className={railLinkClass}>
            <Icon size={18} />
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto flex flex-col items-center gap-2">
        <NavLink to="/settings" title="Settings" aria-label="Settings" className={railLinkClass}>
          <SettingsIcon size={18} />
        </NavLink>
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Account"
            aria-expanded={menuOpen}
            className="grid h-11 w-11 place-items-center rounded-full"
          >
            <Avatar name={displayName} size={32} />
          </button>
          {menuOpen && (
            <div className="absolute bottom-0 left-full z-50 ml-2 w-56 rounded-card border border-border bg-surface p-3 shadow-2xl">
              <div className="truncate text-sm font-semibold">{displayName}</div>
              <div className="mt-0.5 flex items-center gap-1 text-xs text-muted">
                <Users size={12} /> {teamName}
              </div>
              <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
                <ThemeToggle />
                <Button variant="ghost" size="sm" onClick={() => supabase.auth.signOut()}>
                  <LogOut size={14} /> Log out
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
