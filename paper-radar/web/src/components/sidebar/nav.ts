import { Bookmark, Image, LayoutGrid, LibraryBig, Map as MapIcon, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Match the path exactly (Home), rather than as a prefix. */
  end?: boolean;
  /** Shows a Beta pill (or "(Beta)" in the collapsed bar). Drop the flag to
   *  graduate a page — nothing else needs to change. */
  beta?: boolean;
  /** Hover text; supplementary, never the only place something is said. */
  description?: (labName: string) => string;
}

/** Yours: what you've done or saved. */
export const PERSONAL_NAV: NavItem[] = [
  { to: "/", label: "Home", icon: LayoutGrid, end: true },
  {
    to: "/reading-list",
    label: "My reading list",
    icon: Bookmark,
    description: () => "Papers you have saved to read",
  },
];

/** The lab's: everything everyone has shared. */
export const LAB_NAV: NavItem[] = [
  {
    to: "/papers",
    label: "Library",
    icon: LibraryBig,
    description: (lab) => `All of ${lab}’s papers`,
  },
  {
    to: "/gallery",
    label: "Figure gallery",
    icon: Image,
    beta: true,
    description: () => "Figures and diagrams your lab has shared",
  },
  {
    to: "/maps",
    label: "Topic map",
    icon: MapIcon,
    beta: true,
    description: () => "See how the lab’s papers connect by subject",
  },
];

/** The label an icon-only control carries: "Topic map (Beta)". */
export function navTitle(item: NavItem): string {
  return item.beta ? `${item.label} (Beta)` : item.label;
}

/** Visible focus ring for every sidebar control. */
export const FOCUS_RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";
