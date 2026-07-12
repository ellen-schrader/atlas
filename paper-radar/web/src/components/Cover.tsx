import { useEffect, useRef } from "react";

import { useTheme } from "@/components/ThemeProvider";
import { drawCover } from "@/lib/cover";
import { cn } from "@/lib/utils";

/** A paper's cover image. Renders `thumbnailUrl` when present, otherwise a
 *  deterministic, theme-aware placeholder keyed by `seed` (the paper id). */
export function Cover({
  seed,
  thumbnailUrl,
  alt = "",
  className,
}: {
  seed: string;
  thumbnailUrl?: string | null;
  alt?: string;
  className?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (thumbnailUrl) return;
    const cv = ref.current;
    if (cv) drawCover(cv, seed, theme === "dark");
  }, [seed, theme, thumbnailUrl]);

  if (thumbnailUrl) {
    return <img src={thumbnailUrl} alt={alt} className={cn("block h-full w-full object-cover", className)} />;
  }
  return (
    <canvas
      ref={ref}
      width={600}
      height={340}
      aria-hidden
      className={cn("block h-full w-full", className)}
    />
  );
}
