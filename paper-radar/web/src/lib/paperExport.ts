/**
 * Serialise a set of papers for handoff out of Atlas — to a chat model (Markdown),
 * to a person over chat/email (plain text), to a reference manager (BibTeX for
 * LaTeX/Zotero, RIS for EndNote/Mendeley), or to a spreadsheet (CSV).
 *
 * Every format shares one normalised {@link ExportPaper} shape, so a list from
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

export type ExportFormat = "markdown" | "text" | "bibtex" | "ris" | "csv";

export interface ExportOptions {
  /** Include each paper's abstract — the "more detailed" version. Off by default,
   *  because a long list of abstracts can overflow a chat model's context. */
  abstracts?: boolean;
  /** A heading for the list (e.g. "Reading list"), used by Markdown/text and to
   *  name the downloaded file. */
  heading?: string;
}

export const FORMAT_META: Record<ExportFormat, { label: string; ext: string; mime: string }> = {
  markdown: { label: "Markdown", ext: "md", mime: "text/markdown" },
  text: { label: "Plain text", ext: "txt", mime: "text/plain" },
  bibtex: { label: "BibTeX", ext: "bib", mime: "application/x-bibtex" },
  ris: { label: "RIS", ext: "ris", mime: "application/x-research-info-systems" },
  csv: { label: "CSV", ext: "csv", mime: "text/csv" },
};

/** Reduce any of the DOI forms our sources store — `10.x/y`, `doi:10.x/y`,
 *  `https://doi.org/…`, the legacy `dx.doi.org`, `www.doi.org` — to the bare DOI.
 *  Exported because the paper detail's DOI link needs the same normalisation: a
 *  second, weaker copy there made Cite and the link disagree about one paper. */
export function bareDoi(doi: string): string {
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

// RIS is a line-based tag format (EndNote, Mendeley, ProCite). One record per
// paper, TY first and ER last; every value must be single-line, so newlines in a
// title or abstract are collapsed. JOUR for a venue-backed paper, GEN otherwise
// (the preprint case), mirroring the @article/@misc split in BibTeX.
function toRis(papers: ExportPaper[], opts: ExportOptions): string {
  return papers
    .map((p) => {
      const lines = [`TY  - ${p.venue ? "JOUR" : "GEN"}`];
      if (p.title) lines.push(`TI  - ${collapse(p.title)}`);
      for (const a of p.authors) lines.push(`AU  - ${risAuthor(a)}`);
      if (p.year != null) lines.push(`PY  - ${p.year}`);
      if (p.venue) lines.push(`JO  - ${collapse(p.venue)}`);
      const doi = p.doi ? bareDoi(p.doi) : null;
      if (doi) lines.push(`DO  - ${doi}`);
      const link = paperLink(p);
      if (link) lines.push(`UR  - ${link}`);
      if (opts.abstracts && p.abstract) lines.push(`AB  - ${collapse(p.abstract)}`);
      lines.push("ER  - ");
      // RIS is conventionally CRLF-delimited; some parsers reject bare LF.
      return lines.join("\r\n");
    })
    .join("\r\n\r\n")
    .concat("\r\n");
}

// A cell a spreadsheet would evaluate rather than display. Excel, Sheets and
// LibreOffice all treat a leading =, +, - or @ as the start of a formula, and
// RFC-4180 quoting does NOT protect you — they strip the quotes first, then
// evaluate. Leading tab/CR are included because they are stripped before that
// test is applied. Paper titles and authors come from scraped publisher metadata
// and from whatever .bib a lab member uploads, so this is attacker-reachable.
const CSV_FORMULA_RE = /^[=+\-@\t\r]/;

/** Quote a CSV cell per RFC 4180, and defuse anything a spreadsheet would run.
 *  The leading apostrophe is the standard mitigation: Excel and Sheets consume
 *  it and show the literal text. */
function csvCell(value: string): string {
  const safe = CSV_FORMULA_RE.test(value) ? `'${value}` : value;
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

function toCsv(papers: ExportPaper[], opts: ExportOptions): string {
  const cols = ["Title", "Authors", "Venue", "Year", "DOI", "URL"];
  if (opts.abstracts) cols.push("Abstract");
  const rows = papers.map((p) => {
    const doi = p.doi ? bareDoi(p.doi) : "";
    const cells = [
      p.title ?? "",
      p.authors.join("; "), // authors within one cell, ";"-joined so the comma stays the delimiter
      p.venue ?? "",
      p.year != null ? String(p.year) : "",
      doi,
      p.url ?? (doi ? `https://doi.org/${doi}` : ""),
    ];
    if (opts.abstracts) cells.push(p.abstract ? collapse(p.abstract) : "");
    return cells.map(csvCell).join(",");
  });
  return [cols.join(","), ...rows].join("\r\n").concat("\r\n");
}

// An initials run: "A", "AB", "A.B.", "X-Y". Every letter must be capital, so a
// real two-letter surname ("Li", "Ng", "Wu") is never mistaken for one.
const INITIALS_RE = /^[A-Z](?:[.-]?[A-Z]){0,2}\.?$/;

/** The family name from any format our sources emit. Crossref gives "Jane Doe",
 *  PubMed gives "Poissonnier A", BibTeX gives "Doe, Jane" — so neither the first
 *  nor the last token is reliably the surname. Mirrors the server's `_surname`
 *  (atlas_mcp/server.py); the "last token" rule made "Poissonnier A" cite as "A". */
/** RIS wants `AU  - Family, Given`. Handed a bare "Jane Doe", EndNote and Zotero
 *  store the whole string as the family name, so the paper cites as "(Jane Doe,
 *  2024)" and sorts under J. BibTeX gets away with raw names because it parses
 *  First-Last itself; RIS does not, so split it here. */
function risAuthor(name: string): string {
  const trimmed = collapse(name);
  if (trimmed.includes(",")) return trimmed; // already Family, Given
  const tokens = trimmed.split(/\s+/).filter(Boolean);
  if (tokens.length < 2) return trimmed;

  // Trailing initials mean the name is already Family-first ("Poissonnier A",
  // "van den Berg JW") — everything before them is the family name, particles
  // and all. surnameOf() can't be reused here: it returns the last token only,
  // which turns "van den Berg" into "Berg".
  const initials: string[] = [];
  while (tokens.length > 1 && INITIALS_RE.test(tokens[tokens.length - 1])) {
    initials.unshift(tokens.pop()!);
  }
  if (initials.length > 0) return `${tokens.join(" ")}, ${initials.join(" ")}`;

  // Otherwise it's Given-first ("Jane Doe"). Walk back over lowercase particles
  // so "Jane van den Berg" keeps its family name intact.
  let i = tokens.length - 1;
  while (i > 1 && /^[a-z]/.test(tokens[i - 1])) i -= 1;
  const family = tokens.slice(i).join(" ");
  const given = tokens.slice(0, i).join(" ");
  return given ? `${family}, ${given}` : family;
}

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
    case "ris":
      return toRis(papers, opts);
    case "csv":
      return toCsv(papers, opts);
  }
}

/** A sensible download filename, e.g. `reading-list-12-papers.bib`. */
export function exportFilename(format: ExportFormat, count: number, heading?: string): string {
  const base = slugify(heading ?? "papers") || "papers";
  return `${base}-${count}-paper${count === 1 ? "" : "s"}.${FORMAT_META[format].ext}`;
}

/** Trigger a browser download of `text` as a file. */
export function downloadText(filename: string, text: string, mime: string): void {
  // Excel on Windows ignores the charset and decodes CSV as the system codepage
  // unless the file opens with a UTF-8 BOM — "Müller" arrives as "MÃ¼ller". Only
  // CSV needs it: the BOM would be literal junk at the top of a .bib or .ris.
  const body = mime === "text/csv" ? ["\ufeff", text] : [text];
  const blob = new Blob(body, { type: `${mime};charset=utf-8` });
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
