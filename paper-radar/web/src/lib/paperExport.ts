/**
 * Serialise a set of papers for handoff out of Atlas — to a chat model (Markdown),
 * to a person over chat/email (plain text), or to a reference manager (BibTeX).
 *
 * The three formats share one normalised {@link ExportPaper} shape, so a list from
 * anywhere in the app (Papers, the Reading List, a single paper) exports the same
 * way. Everything here is pure and side-effect free except {@link downloadText},
 * which the browser needs to save a file.
 */

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

/** The best public link for a paper: its DOI resolver, falling back to the raw URL. */
export function paperLink(p: ExportPaper): string | null {
  if (p.doi) return `https://doi.org/${p.doi.replace(/^https?:\/\/doi\.org\//i, "")}`;
  return p.url ?? null;
}

function sourceLine(p: ExportPaper): string {
  const bits = [p.venue, p.year != null ? String(p.year) : null].filter(Boolean);
  return bits.join(" ");
}

function toMarkdown(papers: ExportPaper[], opts: ExportOptions): string {
  const title = opts.heading ?? "Papers";
  const head = `# ${title} (${papers.length} paper${papers.length === 1 ? "" : "s"})`;
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
  return [head, "", blocks.join("\n\n"), ""].join("\n");
}

function toText(papers: ExportPaper[], opts: ExportOptions): string {
  const title = opts.heading ?? "Papers";
  const head = `${title} (${papers.length} paper${papers.length === 1 ? "" : "s"})`;
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
  return [head, "", blocks.join("\n\n"), ""].join("\n");
}

function toBibtex(papers: ExportPaper[], opts: ExportOptions): string {
  const used = new Set<string>();
  return papers
    .map((p) => {
      const key = uniqueKey(bibKey(p), used);
      // A preprint with no venue/year is closer to @misc than @article.
      const type = p.venue || p.year != null ? "article" : "misc";
      const fields: [string, string][] = [];
      if (p.title) fields.push(["title", p.title]);
      if (p.authors.length) fields.push(["author", p.authors.map(bibEscape).join(" and ")]);
      if (p.year != null) fields.push(["year", String(p.year)]);
      if (p.venue) fields.push([type === "article" ? "journal" : "howpublished", p.venue]);
      const doi = p.doi?.replace(/^https?:\/\/doi\.org\//i, "");
      if (doi) fields.push(["doi", doi]);
      const link = p.url ?? (doi ? `https://doi.org/${doi}` : null);
      if (link) fields.push(["url", link]);
      if (opts.abstracts && p.abstract) fields.push(["abstract", collapse(p.abstract)]);

      const body = fields
        // author is already escaped ("A and B"); everything else gets escaped here.
        .map(([k, v]) => `  ${k} = {${k === "author" ? v : bibEscape(v)}}`)
        .join(",\n");
      return `@${type}{${key},\n${body}\n}`;
    })
    .join("\n\n")
    .concat("\n");
}

/** BibTeX cite key: FirstAuthorSurname + Year + first title word, e.g. `okonkwo2023retina`. */
function bibKey(p: ExportPaper): string {
  const surname = p.authors[0]
    ? p.authors[0]
        .replace(/,.*$/, "") // "Okonkwo, K." -> "Okonkwo"
        .trim()
        .split(/\s+/)
        .pop() ?? ""
    : "";
  const word =
    p.title
      ?.toLowerCase()
      .replace(/[^a-z0-9\s]/g, "")
      .split(/\s+/)
      .find((w) => w.length > 3) ?? "";
  const key = `${surname}${p.year ?? ""}${word}`.replace(/[^A-Za-z0-9]/g, "");
  return key.toLowerCase() || "ref";
}

function uniqueKey(base: string, used: Set<string>): string {
  let key = base;
  let n = 1;
  // Collisions (same author, year, title word) would make two @entries share a key,
  // which reference managers silently merge — suffix a, b, c… instead.
  while (used.has(key)) key = `${base}${String.fromCharCode(96 + ++n)}`;
  used.add(key);
  return key;
}

/** Escape the characters that are syntactically special in a BibTeX brace value. */
function bibEscape(s: string): string {
  return s
    .replace(/\\/g, "\\textbackslash{}")
    .replace(/[{}]/g, "\\$&")
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
  const base = (heading ?? "papers")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `${base || "papers"}-${count}-paper${count === 1 ? "" : "s"}.${FORMAT_META[format].ext}`;
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
