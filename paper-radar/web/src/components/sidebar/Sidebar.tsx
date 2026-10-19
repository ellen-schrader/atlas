import { NavLink } from "react-router-dom";

import { AtlasMark, Brand } from "@/components/Brand";
import { NotificationsBell } from "@/components/NotificationsBell";
import type { Team } from "@/lib/types";
import { cn } from "@/lib/utils";

import { ClaudeButton, ClaudeRow } from "./ClaudeEntry";
import { FOCUS_RING, HOME_NAV, NAV_GROUPS, type NavItem, navTitle, visible } from "./nav";
import { ProfileMenu } from "./ProfileMenu";

export interface SidebarProps {
  userId: string;
  email: string;
  displayName: string;
  team: Team;
  labs: Team[];
  onSwitchLab: (teamId: string) => boolean;
  /** Features on for the user in this lab (public.my_features). */
  features: readonly string[];
}

function NavRow({
  item,
  labName,
  tall,
  onNavigate,
}: {
  item: NavItem;
  labName: string;
  tall: boolean;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      title={item.description?.(labName)}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-control px-2.5 text-sm font-medium transition",
          tall ? "min-h-11" : "min-h-9",
          isActive ? "bg-accent-weak text-accent" : "text-muted hover:bg-surface-2 hover:text-fg",
          FOCUS_RING,
        )
      }
    >
      <Icon size={16} strokeWidth={2} aria-hidden className="shrink-0" />
      <span className="min-w-0 truncate">{item.label}</span>
      {/* Grey on purpose: cyan in the sidebar means "you are here" and nothing else. */}
      {item.beta && (
        <span className="ml-auto shrink-0 rounded-full border border-border-strong px-1.5 py-[3px] text-[10px] font-semibold uppercase leading-none tracking-[0.04em] text-muted">
          Beta
        </span>
      )}
    </NavLink>
  );
}

/** The labelled sidebar: desktop, and the mobile drawer (`drawer` grows the
 *  rows to 44px touch targets). Home, then the headed groups. */
export function Sidebar({
  drawer = false,
  onNavigate,
  ...p
}: SidebarProps & { drawer?: boolean; onNavigate?: () => void }) {
  const navGroup = (label: string, items: NavItem[]) => (
    <nav aria-label={label} className="flex flex-col gap-0.5">
      {items.map((item) => (
        <NavRow key={item.to} item={item} labName={p.team.name} tall={drawer} onNavigate={onNavigate} />
      ))}
    </nav>
  );

  return (
    <>
      <div className="flex items-center justify-between px-1">
        <Brand size={24} />
        {/* Not in the drawer: the top bar behind it already has one, and its
            320px dropdown doesn't fit a 280px drawer. */}
        {!drawer && <NotificationsBell userId={p.userId} align="left" />}
      </div>

      {navGroup("Main", HOME_NAV)}
      {NAV_GROUPS.map((g) => {
        const items = visible(g.items, p.features);
        if (items.length === 0) return null;
        return (
          <div key={g.label} className="flex flex-col gap-1">
            <div className="flex items-center gap-2 px-2.5 text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
              {g.label}
              {g.pill && (
                <span className="rounded-full border border-border-strong px-1.5 py-[3px] text-[10px] leading-none text-muted">
                  {g.pill}
                </span>
              )}
            </div>
            {navGroup(g.label, items)}
          </div>
        );
      })}

      <div className="mt-auto">
        <ClaudeRow teamId={p.team.id} userId={p.userId} onNavigate={onNavigate} />
      </div>

      <div className="border-t border-border pt-4">
        <ProfileMenu variant="row" {...p} onNavigate={onNavigate} />
      </div>
    </>
  );
}

/** The 68px icon bar between phone and wide-desktop widths. Same items, same
 *  order; labels (and Beta) move into tooltips and aria-labels. */
export function CollapsedBar(p: SidebarProps) {
  const icon = (item: NavItem) => {
    const Icon = item.icon;
    const label = navTitle(item);
    return (
      <NavLink
        key={item.to}
        to={item.to}
        end={item.end}
        title={label}
        aria-label={label}
        className={({ isActive }) =>
          cn(
            "grid h-11 w-11 place-items-center rounded-[10px] transition",
            isActive ? "bg-accent-weak text-accent" : "text-muted hover:bg-surface-2 hover:text-fg",
            FOCUS_RING,
          )
        }
      >
        <Icon size={18} aria-hidden />
      </NavLink>
    );
  };

  return (
    <aside className="flex h-full w-[68px] shrink-0 flex-col items-center gap-4 overflow-y-auto border-r border-border bg-surface py-4">
      <span className="grid h-11 w-11 shrink-0 place-items-center" title="Atlas">
        <AtlasMark size={24} className="text-accent" />
      </span>

      <div className="flex flex-col items-center gap-1">
        <nav aria-label="Main" className="flex flex-col items-center gap-1">
          {HOME_NAV.map(icon)}
        </nav>
        {NAV_GROUPS.map((g) => {
          const items = visible(g.items, p.features);
          return (
            items.length > 0 && (
              // The headings don't fit 68px: a hairline marks where a group starts.
              <nav
                key={g.label}
                aria-label={g.label}
                className="mt-1 flex flex-col items-center gap-1 border-t border-border pt-2"
              >
                {items.map(icon)}
              </nav>
            )
          );
        })}
      </div>

      <div className="mt-auto flex flex-col items-center gap-2">
        <ClaudeButton teamId={p.team.id} userId={p.userId} />
        <ProfileMenu variant="avatar" {...p} />
      </div>
    </aside>
  );
}
