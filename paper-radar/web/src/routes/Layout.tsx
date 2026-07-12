import type { Session } from "@supabase/supabase-js";
import { useState } from "react";
import { NavLink, Outlet, useOutletContext } from "react-router-dom";
import {
  Compass,
  LayoutGrid,
  LibraryBig,
  LogOut,
  Map as MapIcon,
  Menu,
  Settings as SettingsIcon,
  Users,
  X,
} from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { PaperModalProvider } from "@/components/PaperModal";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
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
];

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-3 rounded-control px-2.5 py-2 text-sm font-medium transition",
    isActive ? "bg-accent-weak text-accent" : "text-muted hover:bg-surface-2 hover:text-fg",
  );

function BrandMark({ size = 7 }: { size?: 6 | 7 }) {
  return (
    <span
      className={cn(
        "grid place-items-center rounded-md bg-accent text-white",
        size === 7 ? "h-7 w-7" : "h-6 w-6",
      )}
    >
      <Compass size={size === 7 ? 16 : 14} />
    </span>
  );
}

export default function Layout({ session, team }: { session: Session; team: Team }) {
  const { data: profile } = useProfile(session.user.id);
  const displayName = profile?.display_name ?? session.user.email ?? "You";
  const ctx: AppContext = { session, team, userId: session.user.id, displayName };
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);

  return (
    <div className="min-h-full">
      {/* mobile top bar */}
      <header className="flex items-center gap-3 border-b border-border bg-surface px-4 py-2.5 md:hidden">
        <button
          aria-label="Open menu"
          onClick={() => setOpen(true)}
          className="grid h-9 w-9 place-items-center rounded-control text-muted transition hover:bg-surface-2 hover:text-fg"
        >
          <Menu size={18} />
        </button>
        <span className="flex items-center gap-2 font-semibold tracking-tight">
          <BrandMark size={6} /> Atlas
        </span>
      </header>

      <div className="flex min-h-full">
        {open && (
          <div
            className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm md:hidden"
            onClick={close}
            aria-hidden
          />
        )}

        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col gap-5 border-r border-border bg-surface p-4",
            "transition-transform md:static md:z-auto md:translate-x-0",
            open ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <div className="flex items-center justify-between px-1">
            <span className="flex items-center gap-2 font-semibold tracking-tight">
              <BrandMark size={7} /> Atlas
            </span>
            <button
              aria-label="Close menu"
              onClick={close}
              className="grid h-8 w-8 place-items-center rounded-control text-muted hover:bg-surface-2 md:hidden"
            >
              <X size={16} />
            </button>
          </div>

          <nav className="flex flex-col gap-0.5">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end} onClick={close} className={linkClass}>
                <Icon size={16} /> {label}
              </NavLink>
            ))}
            <span
              aria-disabled
              className="flex cursor-default items-center gap-3 rounded-control px-2.5 py-2 text-sm font-medium text-faint"
              title="Coming soon"
            >
              <MapIcon size={16} /> Map
              <span className="ml-auto rounded-full bg-surface-3 px-2 py-0.5 text-[11px] font-semibold text-muted">
                soon
              </span>
            </span>
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

        <main className="min-w-0 flex-1 overflow-auto">
          <PaperModalProvider teamId={team.id} userId={session.user.id}>
            <Outlet context={ctx} />
          </PaperModalProvider>
        </main>
      </div>
    </div>
  );
}
