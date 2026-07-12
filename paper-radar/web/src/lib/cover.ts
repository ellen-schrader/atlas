// Deterministic, theme-aware cover art for a paper — a placeholder until a real
// thumbnail is available. Light theme evokes H&E histology (deep magenta/purple
// pigment on a warm ground); dark evokes immunofluorescence (glowing cyan/
// magenta/violet on near-black). Same seed → same image, so covers are stable.

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
  const hues = dark ? [188, 314, 266, 150, 332] : [325, 300, 265, 340, 285];
  ctx.fillStyle = dark ? "#080b11" : "#ebe4ec";
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
      g.addColorStop(0, `hsla(${hue},58%,63%,0.9)`);
      g.addColorStop(1, `hsla(${hue},58%,63%,0)`);
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
  vg.addColorStop(1, dark ? "rgba(0,0,0,0.5)" : "rgba(45,20,45,0.08)");
  ctx.fillStyle = vg;
  ctx.fillRect(0, 0, w, h);
}
