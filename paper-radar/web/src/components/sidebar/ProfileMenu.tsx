import { type KeyboardEvent, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeftRight,
  Bell,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  LogOut,
  Moon,
  Settings as SettingsIcon,
  Sun,
} from "lucide-react";

import { NotificationsList, useUnseenMentions } from "@/components/NotificationsBell";
import { useTheme, type Theme } from "@/components/ThemeProvider";
import { useDismissable } from "@/hooks/useDismissable";
import { supabase } from "@/lib/supabase";
import type { Team } from "@/lib/types";
import { cn, initials } from "@/lib/utils";

import { FOCUS_RING } from "./nav";

interface Props {
  userId: string;
  /** "row": the sidebar's profile row, menu above it at the same width.
   *  "avatar": the collapsed bar's button, menu out to the right of the bar. */
  variant: "row" | "avatar";
  displayName: string;
  email: string;
  team: Team;
  labs: Team[];
  onSwitchLab: (teamId: string) => boolean;
  onNavigate?: () => void;
}

/** Initials on a --danger tint: the account is the one place in the chrome
 *  that's about *you*, and it shouldn't read as another nav item. */
function ProfileAvatar({ name }: { name: string }) {
  return (
    <span
      aria-hidden
      className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-danger/15 text-[13px] font-semibold text-danger"
    >
      {initials(name)}
    </span>
  );
}

const ITEM = cn(
  "flex w-full items-center gap-2.5 rounded-[7px] px-2.5 py-2 text-left text-[13px] font-medium text-fg transition",
  "hover:bg-border",
  FOCUS_RING,
);

const ITEM_ROLES = '[role="menuitem"], [role="menuitemradio"]';

/** Everything account-related: settings, lab, theme, log out. Opens above its
 *  trigger, `position: fixed` so the sidebar's own scroll can't clip it. */
export function ProfileMenu({
  userId,
  variant,
  displayName,
  email,
  team,
  labs,
  onSwitchLab,
  onNavigate,
}: Props) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"main" | "labs" | "notifications">("main");
  const [switchFailed, setSwitchFailed] = useState(false);
  const [pos, setPos] = useState<{ left: number; bottom: number; width: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const { theme, setTheme } = useTheme();
  // The collapsed bar has no bell, so its menu carries notifications instead,
  // and the avatar wears the unread dot the bell would have.
  const withNotifications = variant === "avatar";
  const unseen = useUnseenMentions(userId).length;

  const close = (returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  };
  // Escape hands focus back to the trigger; a click elsewhere leaves it where
  // the user put it.
  useDismissable(wrapRef, open, (reason) => close(reason === "escape"));

  const place = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setPos(
      variant === "row"
        ? { left: rect.left, bottom: window.innerHeight - rect.top + 6, width: rect.width }
        : // Out to the right of the bar, bottom-aligned with the avatar (spec:
          // left 76 / bottom 12 for a full-height bar — this is the same spot,
          // measured, so it holds when the bar scrolls or the shell is inset).
          {
            // The bar's edge, not the avatar's: the avatar sits centred in it.
            left: (triggerRef.current?.closest("aside")?.getBoundingClientRect().right ?? rect.right) + 8,
            bottom: Math.max(8, window.innerHeight - rect.bottom),
            width: 240,
          },
    );
  };

  // A resize would leave a fixed panel hanging where the trigger used to be.
  useEffect(() => {
    if (!open) return;
    const onResize = () => close(false);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open]);

  // Focus the first item whenever the menu (or its lab sub-view) appears.
  useLayoutEffect(() => {
    if (open) panelRef.current?.querySelector<HTMLElement>(ITEM_ROLES)?.focus();
  }, [open, view]);

  const toggle = () => {
    if (open) return close(false);
    place();
    setView("main");
    setSwitchFailed(false);
    setOpen(true);
  };

  const onPanelKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(ITEM_ROLES) ?? []);
    const i = items.indexOf(document.activeElement as HTMLElement);
    const go = (n: number) => {
      e.preventDefault();
      items[(n + items.length) % items.length]?.focus();
    };
    if (e.key === "ArrowDown") go(i + 1);
    else if (e.key === "ArrowUp") go(i < 0 ? -1 : i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(-1);
    else if (e.key === "Tab") {
      e.preventDefault();
      close(true);
    }
  };

  const currentLab = team;
  const multiLab = labs.length > 1;

  return (
    <div ref={wrapRef}>
      {variant === "row" ? (
        <button
          ref={triggerRef}
          type="button"
          onClick={toggle}
          aria-haspopup="menu"
          aria-expanded={open}
          className={cn(
            "flex w-full items-center gap-2.5 rounded-control p-2 text-left transition hover:bg-surface-2",
            FOCUS_RING,
          )}
        >
          <ProfileAvatar name={displayName} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold text-fg">{displayName}</span>
            <span className="block truncate text-xs text-muted">{team.name}</span>
          </span>
          <ChevronsUpDown size={14} className="shrink-0 text-muted" aria-hidden />
        </button>
      ) : (
        <button
          ref={triggerRef}
          type="button"
          onClick={toggle}
          aria-label={unseen ? `Account, ${unseen} unread notifications` : "Account"}
          title="Account"
          aria-haspopup="menu"
          aria-expanded={open}
          className={cn("relative grid h-11 w-11 place-items-center rounded-full", FOCUS_RING)}
        >
          <ProfileAvatar name={displayName} />
          {unseen > 0 && (
            <span
              aria-hidden
              className="absolute right-1.5 top-1.5 h-[7px] w-[7px] rounded-full bg-accent ring-2 ring-surface"
            />
          )}
        </button>
      )}

      {open && pos && (
        <div
          ref={panelRef}
          role="menu"
          aria-label="Account"
          onKeyDown={onPanelKey}
          style={{
            left: pos.left,
            bottom: pos.bottom,
            width: view === "notifications" ? Math.min(320, window.innerWidth - pos.left - 8) : pos.width,
          }}
          className="fixed z-50 overflow-hidden rounded-[10px] border border-border-strong bg-surface-2 p-1.5 shadow-[0_12px_32px_rgba(0,0,0,.45)]"
        >
          {view === "main" ? (
            <>
              <div className="px-2.5 pb-2 pt-1.5">
                <div className="truncate text-[13px] font-semibold text-fg">{displayName}</div>
                <div className="truncate text-xs text-muted" title={email}>
                  {email}
                </div>
              </div>

              {withNotifications && (
                <button
                  type="button"
                  role="menuitem"
                  aria-haspopup="menu"
                  className={ITEM}
                  onClick={() => setView("notifications")}
                >
                  <MenuIcon>
                    <Bell size={15} />
                  </MenuIcon>
                  <span>Notifications</span>
                  {unseen > 0 && (
                    <span className="ml-auto text-xs tabular-nums text-muted">{unseen} unread</span>
                  )}
                  <ChevronRight
                    size={14}
                    className={cn("shrink-0 text-muted", unseen === 0 && "ml-auto")}
                    aria-hidden
                  />
                </button>
              )}

              <Link
                to="/settings"
                role="menuitem"
                className={ITEM}
                onClick={() => {
                  close(false);
                  onNavigate?.();
                }}
              >
                <MenuIcon>
                  <SettingsIcon size={15} />
                </MenuIcon>
                Settings
              </Link>

              {multiLab && (
                <button
                  type="button"
                  role="menuitem"
                  aria-haspopup="menu"
                  className={ITEM}
                  onClick={() => setView("labs")}
                >
                  <MenuIcon>
                    <ArrowLeftRight size={15} />
                  </MenuIcon>
                  <span className="shrink-0">Switch lab</span>
                  <span className="ml-auto min-w-0 truncate text-xs text-muted" title={currentLab.name}>
                    {currentLab.name}
                  </span>
                  <ChevronRight size={14} className="shrink-0 text-muted" aria-hidden />
                </button>
              )}

              <div className="flex items-center gap-2.5 px-2.5 py-1.5 text-[13px] font-medium text-fg">
                <MenuIcon>{theme === "dark" ? <Moon size={15} /> : <Sun size={15} />}</MenuIcon>
                <span id="profile-menu-theme">Theme</span>
                <div
                  role="group"
                  aria-labelledby="profile-menu-theme"
                  className="ml-auto flex rounded-[7px] border border-border-strong p-0.5"
                >
                  {(["dark", "light"] as Theme[]).map((t) => (
                    <button
                      key={t}
                      type="button"
                      role="menuitemradio"
                      aria-checked={theme === t}
                      // Stays open: you want to see the change before you go.
                      onClick={() => setTheme(t)}
                      className={cn(
                        "rounded-[5px] px-2 py-0.5 text-xs font-medium capitalize transition",
                        theme === t ? "bg-border text-fg" : "text-muted hover:text-fg",
                        FOCUS_RING,
                      )}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              <div role="separator" className="mx-1 my-1 h-px bg-border" />

              <button
                type="button"
                role="menuitem"
                className={ITEM}
                onClick={() => {
                  close(false);
                  void supabase.auth.signOut();
                }}
              >
                <MenuIcon>
                  <LogOut size={15} />
                </MenuIcon>
                Log out
              </button>
            </>
          ) : view === "notifications" ? (
            <>
              <button type="button" role="menuitem" className={ITEM} onClick={() => setView("main")}>
                <MenuIcon>
                  <ChevronLeft size={15} />
                </MenuIcon>
                Back
              </button>
              <div className="-mx-1.5 -mb-1.5 mt-1 border-t border-border">
                <NotificationsList
                  userId={userId}
                  inMenu
                  onOpened={() => close(false)}
                  // "Mark all read" unmounts itself and every row; without this
                  // a keyboard user's focus falls to <body> and the menu is stranded.
                  onMarkedAll={() =>
                    panelRef.current?.querySelector<HTMLElement>(ITEM_ROLES)?.focus()
                  }
                />
              </div>
            </>
          ) : (
            <>
              <button type="button" role="menuitem" className={ITEM} onClick={() => setView("main")}>
                <MenuIcon>
                  <ChevronLeft size={15} />
                </MenuIcon>
                Switch lab
              </button>
              <div role="separator" className="mx-1 my-1 h-px bg-border" />
              {labs.map((lab) => (
                <button
                  key={lab.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={lab.id === currentLab.id}
                  className={ITEM}
                  onClick={() => {
                    if (lab.id === currentLab.id) return close(true);
                    if (!onSwitchLab(lab.id)) setSwitchFailed(true);
                  }}
                >
                  <MenuIcon>{lab.id === currentLab.id && <Check size={15} />}</MenuIcon>
                  <span className="min-w-0 truncate">{lab.name}</span>
                </button>
              ))}
              {switchFailed && (
                <p role="alert" className="px-2.5 pb-1.5 pt-2 text-xs text-danger">
                  Couldn’t switch: this browser is blocking site storage, which Atlas needs to
                  remember your lab.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function MenuIcon({ children }: { children?: ReactNode }) {
  return (
    <span aria-hidden className="grid w-[15px] shrink-0 place-items-center text-muted">
      {children}
    </span>
  );
}
