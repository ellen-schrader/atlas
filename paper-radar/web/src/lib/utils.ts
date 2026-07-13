import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Turn a lab name into a URL-safe display slug (NOT the join code). */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * Return `url` only if it is a safe link/href target (http, https, or mailto).
 * Guards against javascript:/data:/vbscript: URLs, which React does NOT block in
 * href/src and would execute on click (stored XSS). Returns undefined otherwise,
 * so the caller renders an inert (non-navigating) link.
 */
export function safeHref(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  const trimmed = url.trim();
  try {
    const { protocol } = new URL(trimmed, window.location.origin);
    return protocol === "http:" || protocol === "https:" || protocol === "mailto:"
      ? trimmed
      : undefined;
  } catch {
    return undefined;
  }
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

/** Relative time like "3d ago", falling back to an absolute date past a month. */
export function formatRelative(iso: string | null): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return "";
  const sec = Math.round((Date.now() - ms) / 1000);
  if (sec < 45) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}d ago`;
  if (day < 30) return `${Math.round(day / 7)}w ago`;
  return formatDate(iso);
}
