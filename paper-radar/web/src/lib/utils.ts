import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Turn a lab name into a URL-safe slug used as its join code. */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Two-letter initials for an avatar, from a name or email. */
export function initials(name: string): string {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** "A. Author, B. Author +3" style author summary. */
export function formatAuthors(authors: string[], max = 3): string {
  if (!authors || authors.length === 0) return "—";
  const shown = authors.slice(0, max).join(", ");
  const extra = authors.length - max;
  return extra > 0 ? `${shown} +${extra}` : shown;
}

/** Short date like "16 Oct 2025". */
export function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
