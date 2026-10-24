import {
  Bookmark,
  Layers,
  FlaskConical,
  Image,
  LayoutGrid,
  LibraryBig,
  Map as MapIcon,
  Radar,
  type LucideIcon,
} from "lucide-react";

import { SAVED_SEARCHES_FEATURE } from "@/lib/savedSearches";
import { TRIALS_FEATURE } from "@/lib/trials";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Match the path exactly (Home), rather than as a prefix. */
  end?: boolean;
  /** Shows a Beta pill (or "(Beta)" in the collapsed bar). Drop the flag to
   *  graduate a page — nothing else needs to change. */
  beta?: boolean;
  /** Only shown when this feature is on for the user in the lab
   *  (public.my_features). Dark features stay out of the nav entirely. */
  feature?: string;
  /** Hover text; supplementary, never the only place something is said. */
  description?: (labName: string) => string;
}

/** Home stands alone, above the headed groups. */
export const HOME_NAV: NavItem[] = [{ to: "/", label: "Home", icon: LayoutGrid, end: true }];

export interface NavGroup {
  /** The group's heading, and its nav landmark's name. */
  label: string;
  /** A pill beside the heading ("New"). */
  pill?: string;
  items: NavItem[];
}

/** The headed groups, in sidebar order. A group whose items are all behind
 *  features the user lacks disappears, heading and all. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Papers",
    items: [
      {
        to: "/papers",
        label: "Library",
        icon: LibraryBig,
        description: (lab) => `All of ${lab}’s papers`,
      },
      {
        to: "/reading-list",
        label: "My reading list",
        icon: Bookmark,
        description: () => "Papers you have saved to read",
      },
      {
        to: "/suggestions",
        label: "Suggestions",
        icon: Radar,
        beta: true,
        feature: SAVED_SEARCHES_FEATURE,
        description: () => "New papers from your saved PubMed, bioRxiv and arXiv searches",
      },
    ],
  },
  {
    label: "Explore",
    items: [
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
    ],
  },
  {
    label: "Clinical trials",
    pill: "New",
    items: [
      {
        to: "/trials/collections",
        label: "Collections",
        icon: Layers,
        feature: TRIALS_FEATURE,
        description: (lab) => `Clinical questions ${lab} follows`,
      },
      {
        to: "/trials",
        label: "All trials",
        icon: FlaskConical,
        // Not a prefix match: /trials/collections is its own entry.
        end: true,
        feature: TRIALS_FEATURE,
        description: (lab) => `Breast cancer trials ${lab} follows`,
      },
    ],
  },
];

/** The items of `items` the user has the features for. */
export function visible(items: NavItem[], features: readonly string[]): NavItem[] {
  return items.filter((item) => !item.feature || features.includes(item.feature));
}

/** The label an icon-only control carries: "Topic map (Beta)". */
export function navTitle(item: NavItem): string {
  return item.beta ? `${item.label} (Beta)` : item.label;
}

/** Visible focus ring for every sidebar control. */
export const FOCUS_RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";
