// Deterministic, theme-aware cover art for a paper — a placeholder until a real
// thumbnail is available. Both themes evoke a multiplexed immunofluorescence panel:
// glowing fluorophore channels (cyan / magenta / violet / green / amber) over the
// app's ground. Same seed → same image, so covers are stable.
//
// The hues are pulled toward the app's channel palette (--ch-1..6 in index.css) —
// the old set was a warm H&E magenta/purple, which now clashes with the cyan accent.

function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(a: number): () => number {
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function drawCover(canvas: HTMLCanvasElement, seed: string, dark: boolean): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.width;
  const h = canvas.height;
  const rnd = mulberry32(hashStr(seed));

  ctx.clearRect(0, 0, w, h);
  // Channel hues: cyan, magenta, violet, green, amber.
  const hues = dark ? [178, 316, 262, 148, 40] : [186, 320, 268, 158, 34];
  ctx.fillStyle = dark ? "#080b11" : "#e7ecec";
  ctx.fillRect(0, 0, w, h);

  ctx.globalCompositeOperation = dark ? "lighter" : "multiply";
  const n = 3 + Math.floor(rnd() * 2);
  for (let i = 0; i < n; i++) {
    const hue = hues[Math.floor(rnd() * hues.length)];
    const x = w * (0.12 + rnd() * 0.76);
    const y = h * (0.1 + rnd() * 0.8);
    const r = Math.min(w, h) * (0.42 + rnd() * 0.5);
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    if (dark) {
      g.addColorStop(0, `hsla(${hue},88%,60%,0.5)`);
      g.addColorStop(0.6, `hsla(${hue},88%,55%,0.14)`);
      g.addColorStop(1, `hsla(${hue},88%,55%,0)`);
    } else {
      // Lighter and less saturated on the slide-glass ground, so covers read as a
      // stained section rather than as a colour field competing with the UI.
      g.addColorStop(0, `hsla(${hue},46%,62%,0.85)`);
      g.addColorStop(1, `hsla(${hue},46%,62%,0)`);
    }
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalCompositeOperation = "source-over";

  const vg = ctx.createRadialGradient(
    w / 2,
    h * 0.42,
    Math.min(w, h) * 0.2,
    w / 2,
    h / 2,
    Math.max(w, h) * 0.72,
  );
  vg.addColorStop(0, "rgba(0,0,0,0)");
  vg.addColorStop(1, dark ? "rgba(0,0,0,0.5)" : "rgba(20,45,45,0.09)");
  ctx.fillStyle = vg;
  ctx.fillRect(0, 0, w, h);
}
