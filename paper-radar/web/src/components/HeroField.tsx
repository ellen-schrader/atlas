import { useEffect, useRef } from "react";

import { usePalette } from "@/lib/palette";

/**
 * The landing hero: a field of points that starts as uniform noise and resolves into
 * themed clusters.
 *
 * It is the product's argument, stated before a word of copy — a firehose of papers
 * becoming a map. It's also the same picture the Overview draws, in the same
 * fluorophore channels, so the marketing and the app are visibly one thing.
 */

const THEMES = [
  { cx: 0.3, cy: 0.44, sd: 0.095 },
  { cx: 0.53, cy: 0.3, sd: 0.085 },
  { cx: 0.7, cy: 0.55, sd: 0.08 },
  { cx: 0.42, cy: 0.7, sd: 0.085 },
  { cx: 0.82, cy: 0.27, sd: 0.06 },
  { cx: 0.19, cy: 0.74, sd: 0.07 },
];

const COUNT = 420;
const SETTLE_SECONDS = 2.6;

/** Deterministic PRNG, so the field looks the same on every load. */
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gauss(r: () => number, mean: number, sd: number) {
  const u = Math.max(1e-9, r());
  return mean + sd * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
}

interface Node {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  theme: number;
  r: number;
  phase: number;
}

function buildNodes(): Node[] {
  const r = rng(20260713);
  return Array.from({ length: COUNT }, () => {
    const theme = Math.floor(r() * THEMES.length);
    const t = THEMES[theme];
    const clamp = (v: number) => Math.min(0.98, Math.max(0.02, v));
    return {
      x0: r(), // the firehose: uniform noise
      y0: r(),
      x1: clamp(gauss(r, t.cx, t.sd * 1.15)), // the map: clustered by meaning
      y1: clamp(gauss(r, t.cy, t.sd * 1.15)),
      theme,
      r: 0.7 + r() * 1.9,
      phase: r() * Math.PI * 2,
    };
  });
}

export function HeroField({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const { categorical } = usePalette();
  // Held in a ref so the animation loop reads current colours without being torn
  // down and restarted whenever the theme flips.
  const colors = useRef(categorical);
  // Written in an effect, not during render: a render that React starts and discards
  // must not mutate anything. `redraw` lets a *static* field (reduced motion, where
  // there is no rAF loop to pick the change up) repaint itself on a theme change.
  const redraw = useRef<(() => void) | null>(null);
  useEffect(() => {
    colors.current = categorical;
    redraw.current?.();
  }, [categorical]);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const nodes = buildNodes();
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf: number | null = null;
    let start: number | null = null;
    // Elapsed time survives a pause, so returning to the hero resumes the settled
    // field instead of rewinding it to noise and replaying the whole intro.
    let elapsed = 0;

    function size() {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas!.width = canvas!.clientWidth * dpr;
      canvas!.height = canvas!.clientHeight * dpr;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function draw(progress: number, seconds: number) {
      const w = canvas!.clientWidth;
      const h = canvas!.clientHeight;
      ctx!.clearRect(0, 0, w, h);
      const eased = 1 - Math.pow(1 - Math.min(1, Math.max(0, progress)), 3);

      for (const n of nodes) {
        // A slow ambient drift once settled, so the field breathes rather than freezing.
        const drift = reduced ? 0 : Math.sin(seconds * 0.35 + n.phase) * 0.0016;
        const x = (n.x0 + (n.x1 - n.x0) * eased + drift) * w;
        const y = (n.y0 + (n.y1 - n.y0) * eased - drift) * h;
        ctx!.beginPath();
        ctx!.arc(x, y, n.r * (0.75 + 0.45 * eased), 0, Math.PI * 2);
        ctx!.fillStyle = colors.current[n.theme % colors.current.length];
        ctx!.globalAlpha = 0.16 + 0.5 * eased;
        ctx!.fill();
      }
      ctx!.globalAlpha = 1;
    }

    function frame(ts: number) {
      if (start === null) start = ts;
      const seconds = elapsed + (ts - start) / 1000;
      draw(seconds / SETTLE_SECONDS, seconds);
      raf = requestAnimationFrame(frame);
    }

    function pause() {
      if (raf === null) return;
      cancelAnimationFrame(raf);
      raf = null;
      elapsed += performance.now() / 1000 - (start ?? performance.now()) / 1000;
      start = null;
    }

    /** Repaint at the current point in time — used for resize and theme changes. */
    function paintNow() {
      draw(reduced ? 1 : elapsed / SETTLE_SECONDS, reduced ? 0 : elapsed);
    }

    size();
    const onResize = () => {
      size();
      if (raf === null) paintNow(); // the rAF loop repaints itself; a paused/static one doesn't
    };
    window.addEventListener("resize", onResize, { passive: true });

    if (reduced) {
      // Honour the preference by showing the *settled* state — the argument the
      // animation makes lives in its destination, so nothing is lost by skipping the
      // journey. There's no loop, so a theme change has to repaint via `redraw`.
      elapsed = SETTLE_SECONDS;
      paintNow();
      redraw.current = paintNow;
    } else {
      raf = requestAnimationFrame(frame);
      redraw.current = () => {
        if (raf === null) paintNow(); // only needed while paused; the loop handles the rest
      };
    }

    // Don't burn a rAF loop on a hero the reader has scrolled past. Resuming carries
    // `elapsed` forward, so the field picks up where it left off.
    const io = new IntersectionObserver(([entry]) => {
      if (reduced) return;
      if (entry.isIntersecting && raf === null) {
        raf = requestAnimationFrame(frame);
      } else if (!entry.isIntersecting) {
        pause();
      }
    });
    io.observe(canvas);

    return () => {
      if (raf !== null) cancelAnimationFrame(raf);
      redraw.current = null;
      io.disconnect();
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return <canvas ref={ref} className={className} aria-hidden />;
}
