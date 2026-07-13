// The data palette, read from the CSS tokens in index.css so there is exactly one
// source of truth. Charts used to hard-code two hex arrays per ramp (light + dark)
// and switch on the theme by hand, which meant the palette lived in two places and
// drifted.
//
// Colour alone is not enough for the categorical scale: six hues is at the limit of
// what's distinguishable, and under deuteranopia (~8% of men) our cyan and magenta
// converge hardest. So the map also encodes theme by SHAPE — see `MARKS`.

import { useMemo } from "react";

import { useTheme } from "@/components/ThemeProvider";

const FALLBACK = "#888888";

/** Read the palette tokens in one pass — getComputedStyle is resolved once, not per token. */
function readTokens(): { token: (name: string) => string; range: (p: string, n: number) => string[] } {
  const style = typeof document === "undefined" ? null : getComputedStyle(document.documentElement);
  const token = (name: string): string => {
    const value = style?.getPropertyValue(name).trim();
    if (!value) {
      // A renamed or dropped token would otherwise degrade silently to grey — which
      // is indistinguishable from --ch-off, i.e. a wrong chart rather than an error.
      if (import.meta.env.DEV && style) console.error(`[palette] missing CSS token ${name}`);
      return FALLBACK;
    }
    return value;
  };
  return { token, range: (p, n) => Array.from({ length: n }, (_, i) => token(`--${p}-${i + 1}`)) };
}

export interface Palette {
  /** Categorical — clusters, venues. Six fluorophore channels. */
  categorical: string[];
  /** Everything outside the top-N categories. */
  other: string;
  /** Sequential, publication year. */
  year: string[];
  /** Sequential, topic relevance. */
  relevance: string[];
}

/**
 * The data palette for the active theme.
 *
 * Safe to resolve during render only because ThemeProvider puts the `.dark` class on
 * <html> in the same tick as the state change — if it lagged a commit, this would
 * cache the outgoing theme's colours.
 */
export function usePalette(): Palette {
  const { theme } = useTheme();
  return useMemo<Palette>(() => {
    const { token, range } = readTokens();
    return {
      categorical: range("ch", CHANNELS),
      other: token("--ch-off"),
      year: range("year", 5),
      relevance: range("rel", 7),
    };
    // `theme` isn't read in the body — it's the invalidation key. The values live in
    // CSS, so the only thing that changes them is the theme flipping.
  }, [theme]);
}

/** One distinct glyph per categorical series, so hue is never the only channel. */
export type Mark = "circle" | "square" | "triangle" | "diamond" | "cross" | "hex";
export const MARKS: Mark[] = ["circle", "square", "triangle", "diamond", "cross", "hex"];

/** How many colours the categorical scale has (--ch-1..--ch-6). */
export const CHANNELS = 6;

/**
 * The glyph for series `index`.
 *
 * The colour cycles with period 6 (`cat[i % 6]`), and `auto_k` can emit up to 8
 * themes — so series 6 and 0 share a hue. If the glyph cycled on the *same*
 * period it would repeat in lockstep and two themes would be identical in both
 * channels, which is precisely the collision the shapes exist to prevent.
 *
 * Offsetting by the lap count (`i + floor(i / 6)`) makes the (colour, glyph)
 * pair unique for the first 36 series: if i ≡ j (mod 6) then i = j + 6k, and the
 * glyph indices differ by 7k ≡ k (mod 6), which is non-zero for 0 < k < 6.
 */
export function markFor(index: number): Mark {
  const i = Math.max(0, Math.trunc(index) || 0);
  const offset = i + Math.floor(i / CHANNELS);
  return MARKS[offset % MARKS.length];
}

/**
 * SVG path for a mark centred on (cx, cy) with radius r. Areas are roughly matched
 * across shapes so no series looks heavier than another.
 */
export function markPath(kind: Mark, cx: number, cy: number, r: number): string {
  const pt = (angle: number, rad: number) =>
    `${(cx + rad * Math.cos(angle)).toFixed(2)},${(cy + rad * Math.sin(angle)).toFixed(2)}`;
  const poly = (angles: number[], rad: number) => `M${angles.map((a) => pt(a, rad)).join("L")}Z`;

  switch (kind) {
    case "square": {
      const h = r * 0.88;
      return `M${cx - h},${cy - h}h${2 * h}v${2 * h}h${-2 * h}Z`;
    }
    case "triangle":
      return poly([-Math.PI / 2, Math.PI / 6, (5 * Math.PI) / 6], r * 1.3);
    case "diamond":
      return poly([-Math.PI / 2, 0, Math.PI / 2, Math.PI], r * 1.35);
    case "hex":
      return poly(
        Array.from({ length: 6 }, (_, i) => (Math.PI / 3) * i - Math.PI / 2),
        r * 1.18,
      );
    case "cross": {
      const a = r * 0.34; // arm half-width
      const b = r * 1.05; // arm length
      return (
        `M${cx - a},${cy - b}h${2 * a}v${b - a}h${b - a}v${2 * a}h${-(b - a)}v${b - a}` +
        `h${-2 * a}v${-(b - a)}h${-(b - a)}v${-2 * a}h${b - a}Z`
      );
    }
    case "circle":
    default: {
      // Two arcs, so a circle is expressible as a path like every other mark.
      return `M${cx - r},${cy}a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0Z`;
    }
  }
}
