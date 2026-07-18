import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Check, Loader2, Search, Wand2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Modal } from "@/components/ui/modal";
import { Textarea } from "@/components/ui/textarea";
import { type PaperFields, postPaper, resolvePaper } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { cn } from "@/lib/utils";

/** Where autofilled metadata came from, in words a researcher recognises. */
const SOURCE_LABEL: Record<string, string> = {
  arxiv: "arXiv",
  crossref: "Crossref",
  pubmed: "PubMed",
  europepmc: "Europe PMC",
  citation_meta: "the publisher’s page",
};

const EMPTY: PaperFields = {
  title: "",
  authors: [],
  venue: "",
  year: null,
  doi: "",
  abstract: "",
  keywords: [],
  source: "manual",
};

/** "look up the URL" → "check and correct" → "added", with "recover" in between when
 *  the page won't resolve.
 *
 *  A bot wall stops us reading the publisher's *page* — it doesn't stop Crossref
 *  reading the paper's *DOI*. So a failed lookup isn't "type it all in yourself",
 *  it's "try the DOI"; typing it all in is only the last resort. */
type Step = "url" | "recover" | "review" | "done";

/** Accept a bare DOI, a `doi:` prefix, or a full doi.org URL — people paste all three.
 *  Returns the bare DOI, which is what `papers.doi` dedupes on: storing the doi.org
 *  URL there instead would never match the same paper added by anyone else. */
function bareDoi(input: string): string | null {
  const doi = input
    .trim()
    .replace(/^doi:\s*/i, "")
    .replace(/^https?:\/\/(dx\.)?doi\.org\//i, "");
  return /^10\.\d{4,9}\/\S+$/.test(doi) ? doi : null;
}

function doiUrl(input: string): string | null {
  const doi = bareDoi(input);
  return doi ? `https://doi.org/${doi}` : null;
}

/** A PubMed article link, or an explicit `pmid:12345`, normalised to the canonical
 *  page — the resolver reads the PMID out of exactly this URL shape. A bare number
 *  is deliberately NOT accepted: "2023" is a valid PMID, so treating stray digits as
 *  one would silently resolve an unrelated paper instead of erroring. */
function pubmedUrl(input: string): string | null {
  const trimmed = input.trim();
  const m =
    trimmed.match(/pubmed\.ncbi\.nlm\.nih\.gov\/([0-9]+)/i) ??
    trimmed.match(/^pmid:\s*([0-9]+)$/i);
  return m ? `https://pubmed.ncbi.nlm.nih.gov/${m[1]}/` : null;
}

/** What people paste is often not a fetchable URL: a bare DOI, a `doi:` handle,
 *  or a scheme-less `arxiv.org/abs/…` (our own placeholder suggests one). The
 *  server only fetches http(s), so build that here rather than bouncing the
 *  paste back with "Only http(s) links can be fetched." */
function fetchableUrl(input: string): string {
  const viaDoi = doiUrl(input);
  if (viaDoi) return viaDoi;
  const trimmed = input.trim();
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) || !trimmed
    ? trimmed
    : `https://${trimmed}`;
}

/** What we'll actually send — the same trimming and DOI normalisation the server sees.
 *  Used both to build the payload and to tell whether the user changed anything. */
function toPayload(fields: PaperFields, authorsText: string): PaperFields {
  return {
    ...fields,
    title: fields.title?.trim() || null,
    venue: fields.venue?.trim() || null,
    // Normalise a pasted doi.org URL down to the bare DOI; keep anything unrecognised
    // as typed rather than silently dropping it.
    doi: bareDoi(fields.doi ?? "") ?? (fields.doi?.trim() || null),
    abstract: fields.abstract?.trim() || null,
    authors: authorsText
      .split("\n")
      .map((a) => a.trim())
      .filter(Boolean),
  };
}

/** Everything except provenance — comparing this to what the resolver gave us is how
 *  we know whether the record is still the resolver's or has become the user's. */
function metaKey(p: PaperFields): string {
  const { source: _source, ...rest } = p;
  return JSON.stringify(rest);
}

export function AddPaperDialog({
  open,
  onClose,
  teamId,
  onAdded,
}: {
  open: boolean;
  onClose: () => void;
  teamId: string;
  /** Called with the new paper's id once it's in the lab (so the list can open it). */
  onAdded?: (paperId: string) => void;
}) {
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>("url");
  const [url, setUrl] = useState("");
  /** The DOI typed on the recover step, when the publisher's page wouldn't load. */
  const [doi, setDoi] = useState("");
  const [fields, setFields] = useState<PaperFields>(EMPTY);
  const [authorsText, setAuthorsText] = useState("");
  const [note, setNote] = useState("");
  /** metaKey() of what the resolver returned; null when nothing was resolved. */
  const [baseline, setBaseline] = useState<string | null>(null);

  const [looking, setLooking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** The paper is already in this lab — found before we write anything. */
  const [duplicate, setDuplicate] = useState<{ paperId: string; title: string | null } | null>(null);
  const [added, setAdded] = useState<{
    paperId: string;
    title: string | null;
    already: boolean;
  } | null>(null);

  const urlRef = useRef<HTMLInputElement>(null);
  const doiRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  // Reset on each open, so a second paper doesn't start inside the last one's state.
  useEffect(() => {
    if (!open) return;
    setStep("url");
    setUrl("");
    setDoi("");
    setFields(EMPTY);
    setAuthorsText("");
    setNote("");
    setBaseline(null);
    setError(null);
    setDuplicate(null);
    setAdded(null);
    setLooking(false);
    setSaving(false);
  }, [open]);

  useEffect(() => {
    if (step === "recover") doiRef.current?.focus();
    // On reaching the review step with nothing filled in, the title is what the user
    // has to type — so start them there.
    if (step === "review" && !fields.title) titleRef.current?.focus();
  }, [step, fields.title]);

  const autofilled = step === "review" && fields.source !== "manual" && Boolean(fields.title);

  /** Fill the form from a resolver hit. `keepUrl` preserves the publisher page the
   *  user actually pasted when the metadata came from its DOI instead — that link is
   *  what their lab will click, and `_upsert_paper` still dedupes on the DOI. */
  function applyResolved(resolved: Awaited<ReturnType<typeof resolvePaper>>) {
    const next: PaperFields = {
      title: resolved.title ?? "",
      authors: resolved.authors ?? [],
      venue: resolved.venue ?? "",
      year: resolved.year,
      doi: resolved.doi ?? "",
      abstract: resolved.abstract ?? "",
      keywords: resolved.keywords ?? [],
      source: resolved.source,
    };
    const authors = (resolved.authors ?? []).join("\n");
    setFields(next);
    setAuthorsText(authors);
    // Remember exactly what the resolver said, so an edit downstream can be detected.
    setBaseline(metaKey(toPayload(next, authors)));
    setStep("review");
  }

  async function lookUp(e: FormEvent) {
    e.preventDefault();
    const value = fetchableUrl(url);
    if (!value) return;
    // Show (and later save) the URL we actually looked up, so a pasted bare DOI
    // becomes its doi.org link everywhere downstream — including `postPaper`.
    setUrl(value);
    setLooking(true);
    setError(null);
    setDuplicate(null);
    try {
      const resolved = await resolvePaper(value);

      // Tell them it's already here BEFORE they fill anything in — the old bar
      // only said so after it had written the post.
      const existing = await findInLab(teamId, resolved.url_norm);
      if (existing) {
        setDuplicate(existing);
        return;
      }

      // No title means nothing got through: a bot wall, or a page with no citation
      // tags. Offer the DOI before making them type the whole record out.
      if (!resolved.title) {
        setDoi(resolved.doi ?? "");
        setStep("recover");
        return;
      }
      applyResolved(resolved);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLooking(false);
    }
  }

  /** The recovery the bot wall leaves open: publishers block the page, not Crossref
   *  or PubMed — so this step takes a DOI, a PubMed link, or a bare PMID. */
  async function lookUpDoi(e: FormEvent) {
    e.preventDefault();
    const target = doiUrl(doi) ?? pubmedUrl(doi);
    if (!target) {
      setError(
        "That doesn’t look like a DOI or a PubMed link. A DOI starts with “10.” — for example 10.1016/j.cell.2023.01.001 — and a PubMed link looks like pubmed.ncbi.nlm.nih.gov/38278431",
      );
      return;
    }
    setLooking(true);
    setError(null);
    try {
      const resolved = await resolvePaper(target);
      if (!resolved.title) {
        setError(
          "That didn’t resolve either. Searching the title on pubmed.ncbi.nlm.nih.gov and pasting the paper’s PubMed link here often works — or add it by hand below.",
        );
        return;
      }
      // The lab may already hold this paper under its doi.org link rather than the
      // publisher URL that was pasted, so re-check before offering to add it again.
      const existing = await findInLab(teamId, resolved.url_norm);
      if (existing) {
        setDuplicate(existing);
        setStep("url");
        return;
      }
      applyResolved(resolved);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLooking(false);
    }
  }

  /** Last resort: type the record out. Keeps whatever URL and DOI we already have.
   *  No baseline — nothing here came from a resolver, so it's "manual" whatever they do. */
  function enterByHand() {
    setFields({ ...EMPTY, doi: bareDoi(doi) ?? "", source: "manual" });
    setAuthorsText("");
    setBaseline(null);
    setError(null);
    setStep("review");
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const draft = toPayload(fields, authorsText);
    // A record the user edited is no longer the resolver's, so don't let
    // `metadata_source` credit Crossref for something a human typed. No baseline
    // (the by-hand path) means it was theirs from the start.
    const edited = baseline === null || metaKey(draft) !== baseline;
    const payload: PaperFields = { ...draft, source: edited ? "manual" : draft.source };
    setSaving(true);
    setError(null);
    try {
      // The review step lets the link be typed by hand, so it can still be a bare
      // DOI or scheme-less — normalise it the same way the lookup path does.
      const r = await postPaper(fetchableUrl(url), teamId, payload, note);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["paper-search", teamId] }),
        qc.invalidateQueries({ queryKey: ["paper-count", teamId] }),
        qc.invalidateQueries({ queryKey: ["team-tags", teamId] }),
        qc.invalidateQueries({ queryKey: ["team-venues", teamId] }),
      ]);
      // Hand-entered links skip the pre-check above, so the server is the only one
      // that knows this was already here. Don't claim we added it if we didn't.
      setAdded({
        paperId: r.paper_id,
        title: r.paper.title ?? payload.title,
        already: r.already_posted,
      });
      setStep("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const canSave = Boolean(url.trim()) && Boolean(fields.title?.trim());

  return (
    <Modal open={open} onClose={onClose} label="Add a paper">
      <div className="flex items-start justify-between gap-4 border-b border-border px-6 py-5 pr-14">
        <div>
          <h2 className="font-serif text-lg font-semibold tracking-tight text-fg">
            {step === "recover"
              ? "Try the DOI or PubMed instead"
              : step !== "done"
                ? "Add a paper"
                : added?.already
                  ? "Already in your lab"
                  : "Added to your lab"}
          </h2>
          <p className="mt-1 text-sm text-muted">
            {step === "url" && "Paste a link — we’ll fill in the details for you."}
            {step === "recover" &&
              "That publisher blocks automated lookups — the paper’s DOI or PubMed page won’t be."}
            {step === "review" &&
              (autofilled
                ? "Check what we found, and fix anything that’s off."
                : "Fill in what you know. A link and a title are all it needs.")}
            {step === "done" &&
              (added?.already
                ? "Someone got there first — nothing was duplicated."
                : "Every paper your lab shares teaches Atlas its taste.")}
          </p>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {step === "url" && (
          <form onSubmit={lookUp} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="paper-url">Paper link or DOI</Label>
              <Input
                id="paper-url"
                ref={urlRef}
                autoFocus
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://doi.org/10.1038/s41586-024-… or arxiv.org/abs/2401.01234"
                disabled={looking}
              />
              <p className="text-xs text-faint">
                arXiv, DOI, PubMed, bioRxiv, or a publisher page.
              </p>
            </div>

            {duplicate && <DuplicateNotice duplicate={duplicate} onClose={onClose} />}
            {error && <ErrorNotice message={error} />}

            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
              <button
                type="button"
                onClick={enterByHand}
                className="text-xs font-medium text-muted underline underline-offset-2 hover:text-fg"
              >
                Enter the details by hand instead
              </button>
              <Button type="submit" disabled={looking || !url.trim()}>
                {looking ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
                {looking ? "Looking it up…" : "Look up"}
              </Button>
            </div>
          </form>
        )}

        {step === "recover" && (
          <form onSubmit={lookUpDoi} className="flex flex-col gap-4">
            <Banner tone="warn" icon={<AlertTriangle size={15} />}>
              We couldn’t read <span className="break-all font-medium">{url.trim()}</span>. Cell,
              ScienceDirect and Wiley block automated lookups of their article pages — but the
              paper’s DOI resolves through Crossref, and its{" "}
              <a
                href="https://pubmed.ncbi.nlm.nih.gov/"
                target="_blank"
                rel="noreferrer"
                className="font-medium underline underline-offset-2"
              >
                PubMed
              </a>{" "}
              page usually works too.
            </Banner>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="paper-doi">DOI or PubMed link</Label>
              <div className="flex gap-2">
                <Input
                  id="paper-doi"
                  ref={doiRef}
                  value={doi}
                  onChange={(e) => setDoi(e.target.value)}
                  placeholder="10.1016/j.cell.2023.01.001 or pubmed.ncbi.nlm.nih.gov/38278431"
                  disabled={looking}
                />
                <Button type="submit" disabled={looking || !doi.trim()} className="shrink-0">
                  {looking ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
                  {looking ? "Looking…" : "Look up"}
                </Button>
              </div>
              <p className="text-xs text-faint">
                The DOI is usually printed under the title, or in the “Cite this article” panel —
                it starts with <span className="font-mono">10.</span> Or search the title on
                PubMed and paste the article’s link.
              </p>
            </div>

            {error && <ErrorNotice message={error} />}

            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
              <button
                type="button"
                onClick={() => {
                  setStep("url");
                  setError(null);
                }}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-muted hover:text-fg"
              >
                <ArrowLeft size={13} /> Use a different link
              </button>
              <button
                type="button"
                onClick={enterByHand}
                className="text-xs font-medium text-muted underline underline-offset-2 hover:text-fg"
              >
                No DOI? Enter the details by hand
              </button>
            </div>
          </form>
        )}

        {step === "review" && (
          <form id="add-paper-form" onSubmit={save} className="flex flex-col gap-4">
            {autofilled ? (
              <Banner tone="ok" icon={<Wand2 size={15} />}>
                Autofilled from{" "}
                <strong className="font-semibold">
                  {SOURCE_LABEL[fields.source] ?? fields.source}
                </strong>
                . Every field is editable.
              </Banner>
            ) : (
              <Banner tone="warn" icon={<AlertTriangle size={15} />}>
                You’re adding this one by hand. A link and a title are all it needs — the abstract
                is what Atlas reads to place the paper on the map, so it’s worth pasting if you
                have it.
              </Banner>
            )}

            {/* The link is the paper's identity (it's what dedup keys off), so it
                stays editable here — the hand-entry path has no other way to set it. */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="f-url">
                Paper link <span className="text-danger">*</span>
              </Label>
              <Input
                id="f-url"
                required
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://www.cell.com/…"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="f-title">
                Title <span className="text-danger">*</span>
              </Label>
              <Input
                id="f-title"
                ref={titleRef}
                required
                value={fields.title ?? ""}
                onChange={(e) => setFields((f) => ({ ...f, title: e.target.value }))}
                placeholder="The paper’s title"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="f-authors">Authors</Label>
              <Textarea
                id="f-authors"
                rows={3}
                value={authorsText}
                onChange={(e) => setAuthorsText(e.target.value)}
                placeholder={"One per line\nAna Silva\nPriya Roy"}
              />
              <p className="text-xs text-faint">One per line, in the order they’re listed.</p>
            </div>

            <div className="grid gap-4 sm:grid-cols-[1fr_7rem]">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="f-venue">Journal or venue</Label>
                <Input
                  id="f-venue"
                  value={fields.venue ?? ""}
                  onChange={(e) => setFields((f) => ({ ...f, venue: e.target.value }))}
                  placeholder="Nature, bioRxiv, NeurIPS…"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="f-year">Year</Label>
                <Input
                  id="f-year"
                  inputMode="numeric"
                  value={fields.year ?? ""}
                  onChange={(e) => {
                    const n = parseInt(e.target.value, 10);
                    setFields((f) => ({ ...f, year: Number.isFinite(n) ? n : null }));
                  }}
                  placeholder="2026"
                />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="f-doi">DOI</Label>
              <Input
                id="f-doi"
                value={fields.doi ?? ""}
                onChange={(e) => setFields((f) => ({ ...f, doi: e.target.value }))}
                placeholder="10.1038/s41586-024-00000-0"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="f-abstract">Abstract</Label>
              <Textarea
                id="f-abstract"
                rows={4}
                value={fields.abstract ?? ""}
                onChange={(e) => setFields((f) => ({ ...f, abstract: e.target.value }))}
                placeholder="Optional — but it’s what Atlas reads to place the paper on the map."
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="f-note">Note to your lab</Label>
              <Textarea
                id="f-note"
                rows={2}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Optional — why should they read it?"
              />
            </div>

            {error && <ErrorNotice message={error} />}
          </form>
        )}

        {step === "done" && added && (
          <div className="flex flex-col items-center gap-4 py-8 text-center">
            <div
              className={cn(
                "grid h-11 w-11 place-items-center rounded-full",
                added.already ? "bg-surface-2 text-muted" : "bg-accent-weak text-accent",
              )}
            >
              {added.already ? <AlertTriangle size={20} /> : <Check size={20} />}
            </div>
            <div className="font-semibold text-fg">{added.title ?? url}</div>
            <div className="flex flex-wrap justify-center gap-2">
              <Button variant="secondary" size="sm" onClick={() => onAdded?.(added.paperId)}>
                Open it
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setStep("url");
                  setUrl("");
                  setDoi("");
                  setFields(EMPTY);
                  setAuthorsText("");
                  setNote("");
                  setBaseline(null);
                  setAdded(null);
                }}
              >
                Add another
              </Button>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-surface-2 px-6 py-3.5">
        {step === "review" ? (
          <>
            <button
              type="button"
              onClick={() => setStep("url")}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-muted hover:text-fg"
            >
              <ArrowLeft size={13} /> Back
            </button>
            <Button type="submit" form="add-paper-form" disabled={saving || !canSave}>
              {saving ? <Loader2 size={15} className="animate-spin" /> : null}
              {saving ? "Adding…" : "Add to lab"}
            </Button>
          </>
        ) : (
          <>
            <p className="text-xs text-faint">
              Adding a back-catalogue?{" "}
              <Link to="/import" onClick={onClose} className="font-medium text-muted underline hover:text-fg">
                Import a .bib file
              </Link>
            </p>
            {step === "done" && (
              <Button variant="secondary" size="sm" onClick={onClose}>
                Done
              </Button>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

/** Is this paper already posted in the lab? Reads through RLS — `papers` is only
 *  visible via a post in one of your labs, which is exactly the question asked. */
async function findInLab(
  teamId: string,
  urlNorm: string,
): Promise<{ paperId: string; title: string | null } | null> {
  const { data, error } = await supabase
    .from("paper_posts")
    .select("paper_id, papers!inner(title, url_norm)")
    .eq("team_id", teamId)
    .eq("papers.url_norm", urlNorm)
    .maybeSingle();
  if (error || !data) return null;
  const papers = data.papers as unknown as { title: string | null };
  return { paperId: data.paper_id as string, title: papers?.title ?? null };
}

function DuplicateNotice({
  duplicate,
  onClose,
}: {
  duplicate: { paperId: string; title: string | null };
  onClose: () => void;
}) {
  return (
    <Banner tone="warn" icon={<AlertTriangle size={15} />}>
      <span className="block">
        Already in your lab: <strong className="font-semibold">{duplicate.title ?? "this paper"}</strong>
      </span>
      <Link
        to={`?paper=${duplicate.paperId}`}
        onClick={onClose}
        className="mt-1 inline-block font-medium underline underline-offset-2"
      >
        Open it instead
      </Link>
    </Banner>
  );
}

function ErrorNotice({ message }: { message: string }) {
  return (
    <Banner tone="error" icon={<AlertTriangle size={15} />}>
      {message}
    </Banner>
  );
}

function Banner({
  tone,
  icon,
  children,
}: {
  tone: "ok" | "warn" | "error";
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-control border px-3 py-2.5 text-xs leading-relaxed",
        tone === "ok" && "border-accent/40 bg-accent-weak text-accent",
        tone === "warn" && "border-border-strong bg-surface-2 text-muted",
        tone === "error" && "border-danger/40 bg-surface-2 text-danger",
      )}
    >
      <span className="mt-px shrink-0">{icon}</span>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
