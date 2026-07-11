import type { Session } from "@supabase/supabase-js";
import { NavLink, Outlet, useOutletContext } from "react-router-dom";
import { Compass, LayoutGrid, LibraryBig, LogOut, Settings as SettingsIcon, Users } from "lucide-react";

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
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

export default function Layout({ session, team }: { session: Session; team: Team }) {
  const { data: profile } = useProfile(session.user.id);
  const displayName = profile?.display_name ?? session.user.email ?? "You";
  const ctx: AppContext = { session, team, userId: session.user.id, displayName };

  return (
    <div className="flex min-h-full">
      <aside className="flex w-60 shrink-0 flex-col gap-4 border-r border-border bg-surface p-4">
        <div className="flex items-center gap-2 px-1 font-semibold tracking-tight">
          <Compass size={20} className="text-accent" /> Atlas
        </div>

        <div className="flex items-center gap-2.5 rounded-md border border-border bg-surface-2 p-2.5">
          <Avatar name={displayName} size={32} />
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">{displayName}</div>
            <div className="flex items-center gap-1 text-xs text-muted">
              <Users size={12} />
              {team.name}
            </div>
          </div>
        </div>

        <nav className="flex flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 rounded-md px-2.5 py-2 text-sm transition",
                  isActive
                    ? "bg-accent/10 font-medium text-accent"
                    : "text-muted hover:bg-surface-2 hover:text-fg",
                )
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto flex items-center justify-between">
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={() => supabase.auth.signOut()}>
            <LogOut size={14} /> Log out
          </Button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <PaperModalProvider teamId={team.id} userId={session.user.id}>
          <Outlet context={ctx} />
        </PaperModalProvider>
      </main>
    </div>
  );
}
