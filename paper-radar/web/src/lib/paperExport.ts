/**
 * Serialise a set of papers for handoff out of Atlas — to a chat model (Markdown),
 * to a person over chat/email (plain text), or to a reference manager (BibTeX).
 *
 * The three formats share one normalised {@link ExportPaper} shape, so a list from
 * anywhere in the app (Papers, the Reading List, a single paper) exports the same
 * way. Everything here is pure and side-effect free except {@link downloadText},
 * which the browser needs to save a file.
 */

import { slugify } from "@/lib/utils";

export interface ExportPaper {
  id: string;
  title: string | null;
  authors: string[];
  venue: string | null;
  year: number | null;
  doi: string | null;
  url: string | null;
  abstract: string | null;
}

export type ExportFormat = "markdown" | "text" | "bibtex";

export interface ExportOptions {
  /** Include each paper's abstract — the "more detailed" version. Off by default,
   *  because a long list of abstracts can overflow a chat model's context. */
  abstracts?: boolean;
  /** A heading for the list (e.g. "Reading list"), used by Markdown/text and to
   *  name the downloaded file. */
  heading?: string;
}

export const FORMAT_META: Record<ExportFormat, { label: string; hint: string; ext: string; mime: string }> = {
  markdown: { label: "Markdown", hint: "for an LLM", ext: "md", mime: "text/markdown" },
  text: { label: "Plain text", hint: "for chat or email", ext: "txt", mime: "text/plain" },
  bibtex: { label: "BibTeX", hint: "for Zotero, Mendeley, EndNote", ext: "bib", mime: "application/x-bibtex" },
};

/** Reduce any of the DOI forms our sources store — `10.x/y`, `doi:10.x/y`,
 *  `https://doi.org/…`, the legacy `dx.doi.org`, `www.doi.org` — to the bare DOI. */
function bareDoi(doi: string): string {
  return doi.trim().replace(/^(?:https?:\/\/)?(?:dx\.|www\.)?doi\.org\/|^doi:\s*/i, "");
}

/** The best public link for a paper: its DOI resolver, falling back to the raw URL. */
export function paperLink(p: ExportPaper): string | null {
  if (p.doi) return `https://doi.org/${bareDoi(p.doi)}`;
  return p.url ?? null;
}

function sourceLine(p: ExportPaper): string {
  const bits = [p.venue, p.year != null ? String(p.year) : null].filter(Boolean);
  return bits.join(" ");
}

// Markdown and plain text are pasted straight into a chat, so they lead with the
// papers — no heading. (BibTeX has no heading either; its entries stand alone.)
function toMarkdown(papers: ExportPaper[], opts: ExportOptions): string {
  const blocks = papers.map((p, i) => {
    const lines = [`${i + 1}. **${p.title ?? p.url ?? "Untitled"}**`];
    const meta = [p.authors.length ? formatAuthorList(p.authors) : null, sourceLine(p) || null]
      .filter(Boolean)
      .join(" · ");
    if (meta) lines.push(`   ${meta}`);
    const link = paperLink(p);
    if (link) lines.push(`   ${link}`);
    if (opts.abstracts && p.abstract) lines.push(`   > ${collapse(p.abstract)}`);
    return lines.join("\n");
  });
  return `${blocks.join("\n\n")}\n`;
}

function toText(papers: ExportPaper[], opts: ExportOptions): string {
  const blocks = papers.map((p, i) => {
    const lines = [`${i + 1}. ${p.title ?? p.url ?? "Untitled"}`];
    const meta = [p.authors.length ? formatAuthorList(p.authors) : null, sourceLine(p) || null]
      .filter(Boolean)
      .join(" — ");
    if (meta) lines.push(`   ${meta}`);
    const link = paperLink(p);
    if (link) lines.push(`   ${link}`);
    if (opts.abstracts && p.abstract) lines.push(`   Abstract: ${collapse(p.abstract)}`);
    return lines.join("\n");
  });
  return `${blocks.join("\n\n")}\n`;
}

function toBibtex(papers: ExportPaper[], opts: ExportOptions): string {
  const used = new Set<string>();
  return papers
    .map((p) => {
      const key = uniqueKey(bibKey(p), used);
      // @article requires a journal, so an entry without a venue is @misc — that's
      // the preprint case (a venue-less paper), regardless of whether it has a year.
      const type = p.venue ? "article" : "misc";
      const fields: [string, string][] = [];
      if (p.title) fields.push(["title", p.title]);
      if (p.authors.length) fields.push(["author", p.authors.map(bibEscape).join(" and ")]);
      if (p.year != null) fields.push(["year", String(p.year)]);
      if (p.venue) fields.push(["journal", p.venue]);
      const doi = p.doi ? bareDoi(p.doi) : null;
      if (doi) fields.push(["doi", doi]);
      const link = p.url ?? (doi ? `https://doi.org/${doi}` : null);
      if (link) fields.push(["url", link]);
      if (opts.abstracts && p.abstract) fields.push(["abstract", collapse(p.abstract)]);

      // doi/url are identifiers — reference managers want them verbatim, so they
      // must NOT go through the LaTeX prose escaper (which would turn `_` into `\_`,
      // `~` into a macro, etc., breaking the link). Everything else is prose.
      const verbatim = new Set(["author", "doi", "url"]);
      const body = fields
        .map(([k, v]) => `  ${k} = {${verbatim.has(k) ? v : bibEscape(v)}}`)
        .join(",\n");
      return `@${type}{${key},\n${body}\n}`;
    })
    .join("\n\n")
    .concat("\n");
}

// An initials run: "A", "AB", "A.B.", "X-Y". Every letter must be capital, so a
// real two-letter surname ("Li", "Ng", "Wu") is never mistaken for one.
const INITIALS_RE = /^[A-Z](?:[.-]?[A-Z]){0,2}\.?$/;

/** The family name from any format our sources emit. Crossref gives "Jane Doe",
 *  PubMed gives "Poissonnier A", BibTeX gives "Doe, Jane" — so neither the first
 *  nor the last token is reliably the surname. Mirrors the server's `_surname`
 *  (atlas_mcp/server.py); the "last token" rule made "Poissonnier A" cite as "A". */
function surnameOf(name: string): string {
  const trimmed = name.trim();
  if (trimmed.includes(",")) {
    const family = trimmed.split(",", 1)[0].trim();
    if (family) return family;
  }
  const tokens = trimmed.split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return "";
  // Drop trailing initials ("Poissonnier A", "van den Berg JW").
  while (tokens.length > 1 && INITIALS_RE.test(tokens[tokens.length - 1])) tokens.pop();
  return tokens[tokens.length - 1];
}

/** Fold accents to ASCII so "Müller" keys as "muller", not "mller". */
function deburr(s: string): string {
  return s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
}

/** BibTeX cite key: FirstAuthorSurname + Year + first title word, e.g. `okonkwo2023retina`. */
function bibKey(p: ExportPaper): string {
  const surname = p.authors[0] ? surnameOf(p.authors[0]) : "";
  const word =
    p.title
      ? deburr(p.title)
          .toLowerCase()
          .replace(/[^a-z0-9\s]/g, "")
          .split(/\s+/)
          .find((w) => w.length > 3) ?? ""
      : "";
  const key = deburr(`${surname}${p.year ?? ""}${word}`).replace(/[^A-Za-z0-9]/g, "");
  return key.toLowerCase() || "ref";
}

function uniqueKey(base: string, used: Set<string>): string {
  // Collisions (same author, year, title word) would make two @entries share a
  // key, which reference managers silently merge — suffix a, b, c…, then -27, -28
  // past the alphabet so the key never gains a non-alphanumeric char.
  let key = base;
  let i = 0;
  while (used.has(key)) {
    i += 1;
    key = `${base}${i <= 26 ? String.fromCharCode(96 + i) : `-${i}`}`;
  }
  used.add(key);
  return key;
}

/** Escape the characters that are syntactically special in a BibTeX brace value. */
function bibEscape(s: string): string {
  // Backslash and braces are handled in one pass: escaping `\` first inserts `{}`
  // that a separate brace pass would then double-escape into `\{\}`.
  return s
    .replace(/[\\{}]/g, (m) => (m === "\\" ? "\\textbackslash{}" : `\\${m}`))
    .replace(/[#$%&_]/g, "\\$&")
    .replace(/~/g, "\\textasciitilde{}")
    .replace(/\^/g, "\\textasciicircum{}");
}

/** Collapse internal whitespace/newlines to single spaces (abstracts are often wrapped). */
function collapse(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

function formatAuthorList(authors: string[], max = 6): string {
  if (authors.length <= max) return authors.join(", ");
  return `${authors.slice(0, max).join(", ")}, et al.`;
}

/** Render a set of papers in the chosen format. */
export function formatPapers(papers: ExportPaper[], format: ExportFormat, opts: ExportOptions = {}): string {
  switch (format) {
    case "markdown":
      return toMarkdown(papers, opts);
    case "text":
      return toText(papers, opts);
    case "bibtex":
      return toBibtex(papers, opts);
  }
}

/** A sensible download filename, e.g. `reading-list-12-papers.bib`. */
export function exportFilename(format: ExportFormat, count: number, heading?: string): string {
  const base = slugify(heading ?? "papers") || "papers";
  return `${base}-${count}-paper${count === 1 ? "" : "s"}.${FORMAT_META[format].ext}`;
}

/** Trigger a browser download of `text` as a file. */
export function downloadText(filename: string, text: string, mime: string): void {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke on the next tick so the click's navigation has a chance to start.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
