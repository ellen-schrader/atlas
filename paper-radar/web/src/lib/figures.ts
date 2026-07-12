import type { Figure } from "@/lib/types";

/** Categories are FREE TEXT and lab-defined (see the mood_board migration). These
 *  are just broad starting suggestions the chooser always offers, on top of the
 *  categories a lab has already coined (public.figure_categories RPC). Stored
 *  verbatim as the display string. Tuned for a spatial-TME + AI lab; labs add
 *  their own from the "+ Add category" control. */
export const DEFAULT_FIGURE_CATEGORIES = [
  "Illustration",
  "Imaging Data",
  "Spatial Map",
  "Analysis",
  "Model & AI",
  "Workflow",
] as const;

/** Display label for a stored category; empty string reads as "Uncategorised". */
export function categoryLabel(value: string): string {
  return value.trim() || "Uncategorised";
}

/** Normalise a category for case-insensitive de-duplication (matching a typed
 *  value against existing ones), without changing what gets stored/displayed. */
export function normalizeCategory(value: string): string {
  return value.trim().toLowerCase();
}

/** Merge default suggestions with a lab's already-used categories, de-duplicated
 *  case-insensitively (a lab's own casing wins over the default's). */
export function mergeCategories(labUsed: string[]): string[] {
  const seen = new Map<string, string>();
  for (const c of labUsed) {
    const t = c.trim();
    if (t) seen.set(normalizeCategory(t), t);
  }
  for (const c of DEFAULT_FIGURE_CATEGORIES) {
    const key = normalizeCategory(c);
    if (!seen.has(key)) seen.set(key, c);
  }
  return [...seen.values()];
}

/** Accepted upload formats. SVG is intentionally excluded (stored-XSS vector);
 *  mirrors the bucket's allowed_mime_types in the migration. */
export const ACCEPTED_MIME = ["image/png", "image/jpeg", "image/webp", "image/gif"] as const;
export const ACCEPTED_EXT: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
};
export const MAX_FILE_BYTES = 10 * 1024 * 1024; // 10 MB, matches the bucket limit

/** Storage bucket name for figure images. */
export const FIGURES_BUCKET = "figures";

/** Build the deterministic object path for a figure: `{team_id}/{figure_id}.{ext}`.
 *  The first segment is what the storage RLS policy checks for lab membership. */
export function figureStoragePath(teamId: string, figureId: string, mime: string): string {
  return `${teamId}/${figureId}.${ACCEPTED_EXT[mime] ?? "png"}`;
}

/** Read an image file's natural pixel dimensions (for stable masonry layout)
 *  without adding it to the DOM. Falls back to an <img> if createImageBitmap
 *  is unavailable. */
export async function readImageSize(file: File): Promise<{ width: number; height: number }> {
  if (typeof createImageBitmap === "function") {
    const bmp = await createImageBitmap(file);
    const size = { width: bmp.width, height: bmp.height };
    bmp.close();
    return size;
  }
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
      URL.revokeObjectURL(url);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Could not read image dimensions"));
    };
    img.src = url;
  });
}

/** Aspect ratio string for a card/img, so layout is stable before the image
 *  loads. Guards against bad stored dimensions. */
export function aspectRatio(f: Pick<Figure, "width" | "height">): string {
  const w = f.width > 0 ? f.width : 4;
  const h = f.height > 0 ? f.height : 3;
  return `${w} / ${h}`;
}
