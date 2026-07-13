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

/** Resolve a CSS custom property off the document root. */
function token(name: string): string {
  if (typeof document === "undefined") return "#888888";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888888";
}

const range = (prefix: string, n: number) =>
  Array.from({ length: n }, (_, i) => token(`--${prefix}-${i + 1}`));

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

/** The data palette for the active theme. Recomputed when the theme flips. */
export function usePalette(): Palette {
  const { theme } = useTheme();
  return useMemo<Palette>(
    () => ({
      categorical: range("ch", 6),
      other: token("--ch-off"),
      year: range("year", 5),
      relevance: range("rel", 7),
    }),
    // `theme` is not read directly — it's the signal that the tokens changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [theme],
  );
}

/** One distinct glyph per categorical series, so hue is never the only channel. */
export type Mark = "circle" | "square" | "triangle" | "diamond" | "cross" | "hex";
export const MARKS: Mark[] = ["circle", "square", "triangle", "diamond", "cross", "hex"];

export function markFor(index: number): Mark {
  return MARKS[((index % MARKS.length) + MARKS.length) % MARKS.length];
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
