import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Download, ExternalLink, Link as LinkIcon, Maximize2, MoreHorizontal, Pencil, Quote, Share2, Trash2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { Avatar } from "@/components/Avatar";
import { BookmarkButton } from "@/components/BookmarkButton";
import { Cover } from "@/components/Cover";
import { PaperEngagement } from "@/components/Engagement";
import { usePaperModal } from "@/components/PaperModal";
import { useMyRole } from "@/hooks/useMyRole";
import { useReadPapers } from "@/hooks/useReadPapers";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import {
  type ExportFormat,
  type ExportPaper,
  FORMAT_META,
  bareDoi,
  downloadText,
  exportFilename,
  formatPapers,
  paperLink,
} from "@/lib/paperExport";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, type PaperCorrection, fixPaperMetadata } from "@/lib/api";
import { loadTeamTags } from "@/lib/filterOptions";
import { useDismissable } from "@/hooks/useDismissable";
import { supabase } from "@/lib/supabase";
import type { Paper, PaperPost, SimilarPaper } from "@/lib/types";
import { cn, formatDate, formatRelative, normaliseTag, safeHref } from "@/lib/utils";

/** Every control in the paper's action row shares these metrics, so labels sit
 *  on one baseline and the row has an even rhythm. Only the colour treatment
 *  differs by tier: filled (primary), outlined (your state), ghost (output). */
const ACTION_BTN =
  "inline-flex h-[38px] shrink-0 items-center gap-1.5 rounded-control px-3 text-sm transition " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

/** Tertiary: no border, muted until hovered. Cite and Share are the same tier,
 *  which is what stops Share reading as a disabled oddity beside outlined
 *  buttons. */
const GHOST_BTN = "font-medium text-muted hover:bg-surface-2 hover:text-fg";

/** Menus float above the card, so they cannot share its background. bg-surface
 *  is exactly the dialog's own colour, which left the abstract legible straight
 *  through the panel; surface-2 plus a real shadow separates them. Right-aligned
 *  to the trigger because every menu in this row now opens from the right side. */
const POPOVER =
  "absolute right-0 top-full z-30 mt-1.5 w-60 overflow-hidden rounded-card border border-border " +
  "bg-surface-2 text-left shadow-[0_8px_24px_rgba(0,0,0,.45)]";

export function PaperDetail({
  post,
  teamId,
  teamName,
  userId,
  bookmarked = false,
  onClose,
  fullPage = false,
}: {
  post: PaperPost;
  teamId: string;
  /** Named in the removal confirmation: "this lab" / "your lab" is vague for
   *  anyone in more than one, and "your" implies ownership they may not have. */
  teamName: string;
  userId: string;
  bookmarked?: boolean;
  onClose?: () => void;
  /** Rendered on its own /papers/:id page rather than inside the modal: the body
   *  flows with the page instead of being a scroll area inside a fixed-height
   *  dialog, and the "Open as page" link is dropped (we are already there). */
  fullPage?: boolean;
}) {
  const p = post.papers;
  const posterName = post.posted_by_label ?? post.poster?.display_name ?? null;
  const canonical = [...new Set([...p.tags, ...p.keywords])];
  const { data: role } = useMyRole(teamId, userId);
  const canDelete = post.posted_by === userId || role === "owner";
  // The API's rule (can_edit_paper) is poster-or-owner in *any* lab holding the
  // paper; this lab's half of it is what the UI can know cheaply, and it is the
  // same gate as removal. The server is the authority either way.
  const canEdit = canDelete;
  const [editing, setEditing] = useState(false);

  return (
    <div className={cn("flex flex-col", !fullPage && "min-h-0 flex-1")}>
      <div className="relative h-[150px] shrink-0">
        <Cover seed={p.id} />
        {!fullPage && (
          // Sits left of Modal's close button (right-3, h-8 w-8) and matches its
          // treatment, so the two read as one set of window controls.
          <Link
            to={`/papers/${p.id}`}
            // Deliberately NOT onClose: the modal lives in the ?paper= search
            // param, and closing it does a replace — which overwrites the
            // ?paper= history entry just before this link pushes, so Back landed
            // on the bare list instead of the dialog you expanded from. Leaving
            // it alone keeps that entry, and the route change unmounts the modal
            // anyway, since ?paper= belongs to the /papers URL.
            aria-label="Open as page"
            title="Open this paper on its own page"
            className="absolute right-3 top-3 z-10 grid h-8 w-8 place-items-center rounded-control bg-black/40 text-white backdrop-blur-sm transition hover:bg-black/60"
          >
            <Maximize2 size={15} />
          </Link>
        )}
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-4">
          {[p.venue, p.year].filter(Boolean).length > 0 && (
            <span className="text-eyebrow font-semibold uppercase tracking-eyebrow tabular-nums text-white/90">
              {[p.venue, p.year].filter(Boolean).join(" · ")}
            </span>
          )}
        </div>
      </div>

      <div className={cn("p-6", !fullPage && "min-h-0 flex-1 overflow-y-auto")}>
        {editing ? (
          <MetadataEditor paper={p} teamId={teamId} onDone={() => setEditing(false)} />
        ) : (
          <>
            <h2 className="text-balance text-[21px] font-bold leading-tight tracking-tight">
              {p.title ?? p.url}
            </h2>
            {p.authors.length > 0 && <AuthorList authors={p.authors} />}
            <PaperIdentifier doi={p.doi} url={p.url} />

            {/* Two clusters, so the row is navigable rather than six equal buttons.
                Left: what you do with the paper and your own state on it. Right,
                pushed over by ml-auto: getting it out of Atlas, then the admin
                action. Within a cluster the gap is 8px; between them at least 24. */}
            <div className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-2">
              <a
                href={safeHref(p.url)}
                target="_blank"
                rel="noreferrer"
                className={cn(ACTION_BTN, "bg-accent font-semibold text-accent-fg hover:brightness-110")}
              >
                Read paper <ExternalLink size={13} />
              </a>
              {safeHref(p.code_url) && <LinkBtn href={safeHref(p.code_url)!}>Code</LinkBtn>}
              {safeHref(p.data_url) && <LinkBtn href={safeHref(p.data_url)!}>Data</LinkBtn>}
              <BookmarkButton
                paperId={p.id}
                teamId={teamId}
                userId={userId}
                bookmarked={bookmarked}
                showLabel
                className={cn(
                  ACTION_BTN,
                  "justify-center border border-border font-medium hover:border-accent hover:text-accent",
                  "aria-pressed:border-accent aria-pressed:bg-accent-weak aria-pressed:text-accent",
                )}
              />
              <MarkReadButton paperId={p.id} teamId={teamId} userId={userId} />

              <span className="ml-auto flex items-center gap-2 pl-6">
                <CitePaperButton
                  paper={{
                    id: p.id,
                    title: p.title,
                    authors: p.authors ?? [],
                    venue: p.venue,
                    year: p.year,
                    doi: p.doi,
                    url: p.url,
                    abstract: p.abstract,
                  }}
                />
                <SharePost paper={p} />
                {(canDelete || canEdit) && (
                  <PostMenu
                    teamId={teamId}
                    teamName={teamName}
                    postId={post.id}
                    canEdit={canEdit}
                    canDelete={canDelete}
                    onFix={() => setEditing(true)}
                    onDeleted={onClose}
                  />
                )}
              </span>
            </div>

            <MetaLabel>Abstract</MetaLabel>
            {p.abstract ? (
              <p className="text-sm leading-relaxed text-fg/90">{p.abstract}</p>
            ) : (
              <p className="text-sm italic text-muted">No abstract available.</p>
            )}
          </>
        )}

        <MetaLabel>Tags</MetaLabel>
        <PaperTags postId={post.id} teamId={teamId} initial={post.tags} canonical={canonical} />

        <div className="mt-5 flex items-center justify-between gap-3 text-xs text-muted">
          <span className="flex items-center gap-2">
            {posterName && <Avatar name={posterName} size={22} />}
            <span title={formatDate(post.posted_at)}>
              Posted {posterName ? `by ${posterName} ` : ""}· {formatRelative(post.posted_at)}
            </span>
          </span>
        </div>
        {p.edited_at && <EditedLine paper={p} userId={userId} />}
        {post.note && (
          <div className="mt-2 rounded-md border border-border bg-surface-2 p-2.5 text-sm text-muted">
            “{post.note}”
          </div>
        )}

        <SimilarPapers paperId={p.id} teamId={teamId} fullPage={fullPage} />

        <hr className="my-6 border-border" />
        <MetaLabel>Discussion</MetaLabel>
        <PaperEngagement paperId={p.id} teamId={teamId} userId={userId} />
      </div>
    </div>
  );
}

/** Copy a link to this paper — for a person, not a bibliography (that is Cite).
 *  Two links, because they answer different questions: the Atlas one keeps the
 *  reader inside the lab's discussion, the publisher one is what you send to
 *  someone who has no Atlas account. */
function SharePost({ paper }: { paper: Paper }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState<"atlas" | "paper" | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);
  useDismissable(ref, open, () => setOpen(false));

  // Absolute, not the in-app route: a link someone pastes into Teams has to
  // work from outside the SPA.
  const atlasUrl = `${window.location.origin}/papers/${paper.id}`;
  // The same DOI-first resolution the exporters use, so a shared link and a
  // copied citation never disagree about where the paper lives.
  const paperUrl = paperLink({
    id: paper.id,
    title: paper.title,
    authors: paper.authors ?? [],
    venue: paper.venue,
    year: paper.year,
    doi: paper.doi,
    url: paper.url,
    abstract: paper.abstract,
  });

  async function copy(which: "atlas" | "paper", value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(which);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(null), 2000);
    } catch {
      // Clipboard blocked: leave the menu open so the link can be selected by
      // hand rather than failing silently.
      window.prompt("Copy this link", value);
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(ACTION_BTN, GHOST_BTN, open && "bg-surface-2 text-fg")}
      >
        <Share2 size={13} /> Share
      </button>
      {open && (
        <div className={POPOVER}>
          <MenuItem
            icon={copied === "atlas" ? <Check size={14} className="text-accent" /> : <LinkIcon size={14} />}
            label={copied === "atlas" ? "Copied" : "Copy Atlas link"}
            hint="Opens the discussion"
            onClick={() => void copy("atlas", atlasUrl)}
          />
          <MenuItem
            icon={copied === "paper" ? <Check size={14} className="text-accent" /> : <ExternalLink size={14} />}
            label={copied === "paper" ? "Copied" : "Copy link to paper"}
            hint={paper.doi ? "Resolves via doi.org" : "The publisher page"}
            disabled={!paperUrl}
            onClick={() => paperUrl && void copy("paper", paperUrl)}
          />
        </div>
      )}
    </div>
  );
}

/** The rare, restricted actions, one step back from the row: editing the
 *  paper (which changes it for every lab holding it) and removing it from this
 *  lab. Neither belongs a stray click away from Save. */
function PostMenu({
  teamId,
  teamName,
  postId,
  canEdit,
  canDelete,
  onFix,
  onDeleted,
}: {
  teamId: string;
  teamName: string;
  postId: string;
  canEdit: boolean;
  canDelete: boolean;
  onFix: () => void;
  onDeleted?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  // A write is in flight. Nothing may close the menu while it is, or the panel
  // unmounts with the request still outstanding and its failure has nowhere to
  // go: the paper stays, and the user is told nothing. Same reason
  // AddPaperDialog refuses to close mid-import.
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  function dismiss(reason: "escape" | "outside") {
    // Swallow the gesture rather than stop listening for it. The hook stops
    // propagation in the capture phase, so staying armed is also what keeps an
    // Escape or a backdrop click from reaching the Modal behind this menu and
    // closing the whole dialog with the write still outstanding.
    if (busy) return;
    setOpen(false);
    // Focus goes back only on Escape. A keyboard user is otherwise dropped at
    // the top of the document — but after a click elsewhere, moving focus onto
    // the trigger that removes a paper for the whole lab means the next Space
    // reopens it.
    if (reason === "escape") trigger.current?.focus();
  }
  useDismissable(ref, open, dismiss);

  // A closed menu is never mid-confirmation. Resetting this where the menu is
  // closed instead — in dismiss() — missed the commonest path: clicking the
  // trigger to close it. The trigger lives inside the dismissable ref, so the
  // outside-click handler deliberately ignores it, and `confirming` survived;
  // reopening the menu then dropped the user straight back into the warning
  // with no way to reach the menu itself. Keyed off `open`, every close path is
  // covered, including ones added later.
  useEffect(() => {
    if (!open) setConfirming(false);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        ref={trigger}
        aria-label="More actions for this paper"
        disabled={busy}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "grid h-[38px] w-[38px] shrink-0 place-items-center rounded-control transition",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          // Visibly open, so the trigger and its menu read as one thing.
          open ? "bg-surface-2 text-fg" : "text-muted hover:bg-surface-2 hover:text-fg",
        )}
      >
        <MoreHorizontal size={16} />
      </button>
      {open && (
        <div className={cn(POPOVER, "w-64")}>
          {confirming ? (
            <DeleteConfirm
              postId={postId}
              teamId={teamId}
              teamName={teamName}
              onCancel={() => setConfirming(false)}
              onBusyChange={setBusy}
              onDeleted={onDeleted}
            />
          ) : (
            <>
              {canEdit && (
                <MenuItem
                  icon={<Pencil size={14} />}
                  label="Edit"
                  onClick={() => {
                    setOpen(false);
                    onFix();
                  }}
                />
              )}
              {canEdit && canDelete && <div className="border-t border-border" role="separator" />}
              {canDelete && (
                <MenuItem
                  icon={<Trash2 size={14} />}
                  // The confirmation that follows names the lab and says who
                  // loses the paper; the menu item doesn't need to rehearse it.
                  label="Delete"
                  danger
                  onClick={() => setConfirming(true)}
                />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** Every cached view of a paper's metadata, so a correction shows everywhere at
 *  once rather than only in the dialog that made it. */
function useRefreshPaper(teamId: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["paper-post"] });
    void qc.invalidateQueries({ queryKey: ["paper-search", teamId] });
    void qc.invalidateQueries({ queryKey: ["reading-list"] });
  };
}

/** The correction form, in place of the paper's header while it is open. Inline
 *  rather than a dialog for the same reason as the removal confirmation: the
 *  detail is often already inside a Modal, and nested focus traps are worse. */
function MetadataEditor({
  paper,
  teamId,
  onDone,
}: {
  paper: Paper;
  teamId: string;
  onDone: () => void;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const refresh = useRefreshPaper(teamId);
  // The token is the edited_at the form was loaded from, captured once: a
  // background refetch must not quietly move it under an open form, or the
  // server could no longer tell that someone else's fix landed meanwhile.
  const [token] = useState(paper.edited_at);
  const [title, setTitle] = useState(paper.title ?? "");
  const [authors, setAuthors] = useState((paper.authors ?? []).join("\n"));
  const [venue, setVenue] = useState(paper.venue ?? "");
  const [year, setYear] = useState(paper.year ? String(paper.year) : "");
  const [abstract, setAbstract] = useState(paper.abstract ?? "");
  const [codeUrl, setCodeUrl] = useState(paper.code_url ?? "");
  const [dataUrl, setDataUrl] = useState(paper.data_url ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; stale: boolean } | null>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => titleRef.current?.focus(), []);

  /** Only what changed: the server holds exactly the fields sent, and a field
   *  re-sent untouched would stop the resolver ever improving it. */
  function changes(): PaperCorrection {
    const out: PaperCorrection = {};
    const text = (v: string) => v.trim() || null;
    if (text(title) !== paper.title) out.title = text(title);
    const list = authors
      .split("\n")
      .map((a) => a.trim())
      .filter(Boolean);
    if (JSON.stringify(list) !== JSON.stringify(paper.authors ?? [])) out.authors = list;
    if (text(venue) !== paper.venue) out.venue = text(venue);
    const y = year.trim() ? Number(year) : null;
    if (y !== paper.year) out.year = y;
    if (text(abstract) !== paper.abstract) out.abstract = text(abstract);
    if (text(codeUrl) !== paper.code_url) out.code_url = text(codeUrl);
    if (text(dataUrl) !== paper.data_url) out.data_url = text(dataUrl);
    return out;
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const fields = changes();
    if (Object.keys(fields).length === 0) {
      onDone();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await fixPaperMetadata(paper.id, token, fields);
      // Write the saved row into the cache before refetching. Reopening the
      // form must read the new edited_at: the old one would send this user's
      // own edit back as "someone else changed this paper".
      qc.setQueriesData<PaperPost | null>({ queryKey: ["paper-post"] }, (old) =>
        old && old.papers.id === paper.id
          ? { ...old, papers: { ...old.papers, ...(result.paper as Partial<Paper>) } }
          : old,
      );
      refresh();
      toast({ message: "Paper updated." });
      onDone();
    } catch (err) {
      const stale = err instanceof ApiError && err.status === 409;
      setError({ message: err instanceof Error ? err.message : String(err), stale });
    } finally {
      setBusy(false);
    }
  }

  function reload() {
    // Throw the form away rather than merge: the other edit may well have fixed
    // what this one was about to.
    refresh();
    onDone();
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-3">
      <h2 className="text-lg font-bold tracking-tight">Edit paper</h2>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="fix-title">
          Title <span className="text-danger">*</span>
        </Label>
        <Input
          id="fix-title"
          ref={titleRef}
          required
          maxLength={2000}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="fix-authors">Authors (one per line)</Label>
        <Textarea
          id="fix-authors"
          rows={3}
          value={authors}
          onChange={(e) => setAuthors(e.target.value)}
        />
      </div>
      <div className="grid grid-cols-[1fr_7rem] gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="fix-venue">Journal or venue</Label>
          <Input id="fix-venue" maxLength={500} value={venue} onChange={(e) => setVenue(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="fix-year">Year</Label>
          <Input
            id="fix-year"
            type="number"
            min={1000}
            max={2200}
            value={year}
            onChange={(e) => setYear(e.target.value)}
          />
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="fix-abstract">Abstract</Label>
        <Textarea
          id="fix-abstract"
          rows={6}
          value={abstract}
          onChange={(e) => setAbstract(e.target.value)}
        />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="fix-code">Code link</Label>
          <Input
            id="fix-code"
            type="url"
            value={codeUrl}
            onChange={(e) => setCodeUrl(e.target.value)}
            placeholder="https://github.com/…"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="fix-data">Data link</Label>
          <Input
            id="fix-data"
            type="url"
            value={dataUrl}
            onChange={(e) => setDataUrl(e.target.value)}
            placeholder="https://zenodo.org/…"
          />
        </div>
      </div>

      {error && (
        <p className="text-xs text-danger">
          {error.message}{" "}
          {error.stale && (
            <button type="button" onClick={reload} className="font-semibold underline">
              Reload
            </button>
          )}
        </p>
      )}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onDone} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy || !title.trim()}>
          {busy ? "Saving…" : "Save for every lab"}
        </Button>
      </div>
    </form>
  );
}

/** "Edited by Ellen · 2 Oct". The editor's name is read under the
 *  caller's own RLS: profiles are visible only to people who share a lab, so for
 *  an editor elsewhere the row simply isn't there, and the line says so rather
 *  than fetching the name with the service role — which would leak who they are
 *  across exactly the boundary that policy draws. */
function EditedLine({ paper, userId }: { paper: Paper; userId: string }) {
  const editor = paper.edited_by;
  const { data: name, isLoading } = useQuery({
    queryKey: ["profile-name", editor],
    enabled: !!editor && editor !== userId,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const { data } = await supabase
        .from("profiles")
        .select("display_name")
        .eq("id", editor!)
        .maybeSingle();
      return (data?.display_name as string | undefined) ?? null;
    },
  });
  if (isLoading) return null;
  const who = !editor
    ? ""
    : editor === userId
      ? " by you"
      : name
        ? ` by ${name}`
        : " outside your lab";
  return (
    <p className="mt-1.5 text-xs text-muted" title={formatDate(paper.edited_at)}>
      Edited{who} · {formatDate(paper.edited_at)}
    </p>
  );
}

function MenuItem({
  icon,
  label,
  hint,
  onClick,
  danger = false,
  disabled = false,
}: {
  icon: ReactNode;
  label: string;
  hint?: string;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm transition",
        "disabled:cursor-not-allowed disabled:opacity-40",
        danger ? "text-danger hover:bg-danger/10" : "text-fg hover:bg-surface-3",
      )}
    >
      <span className="shrink-0">{icon}</span>
      <span className="min-w-0">
        <span className="block truncate font-medium">{label}</span>
        {hint && <span className="block truncate text-xs text-faint">{hint}</span>}
      </span>
    </button>
  );
}

/** The confirmation, inline in the menu rather than a dialog: the paper detail
 *  is already a Modal, and stacking one focus trap inside another is worse than
 *  the small panel this replaces it with. */
function DeleteConfirm({
  postId,
  teamId,
  teamName,
  onCancel,
  onBusyChange,
  onDeleted,
}: {
  postId: string;
  teamId: string;
  teamName: string;
  onCancel: () => void;
  /** Tells the menu a removal is in flight, so it refuses to close over it. */
  onBusyChange: (busy: boolean) => void;
  onDeleted?: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  // Focus the safe choice: this appears under the pointer, and Enter must not
  // be the key that removes a paper for a whole lab.
  useEffect(() => cancelRef.current?.focus(), []);

  // Belt and braces: if this ever does unmount mid-write, the menu must not be
  // left latched shut.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => () => onBusyChange(false), []);

  function refresh() {
    void qc.invalidateQueries({ queryKey: ["paper-post", teamId] });
    void qc.invalidateQueries({ queryKey: ["paper-search", teamId] });
    void qc.invalidateQueries({ queryKey: ["paper-count", teamId] });
    void qc.invalidateQueries({ queryKey: ["team-tags", teamId] });
    void qc.invalidateQueries({ queryKey: ["reading-list"] });
  }

  function markBusy(b: boolean) {
    setBusy(b);
    onBusyChange(b);
  }

  async function del() {
    markBusy(true);
    setError(null);
    // .select(), so a delete that matched nothing is distinguishable from one
    // that worked: PostgREST answers 204 with no error when RLS or a race
    // filters every candidate row. Without this, a stale dialog (someone else
    // removed the paper first) reported success and then offered an Undo that
    // would have reverted *their* removal.
    const { data, error: err } = await supabase
      .from("paper_posts")
      .delete()
      .eq("id", postId)
      .select("id");
    // Released only here: until this point the menu holds itself open, so the
    // messages below are rendered rather than set on an unmounted component.
    markBusy(false);
    if (err) {
      setError(err.message);
      return;
    }
    if (!data || data.length === 0) {
      setError("That paper has already been removed.");
      refresh();
      return;
    }
    refresh();
    // Removing closes this dialog, so the way back has to live outside it.
    // restore_post takes only the removal's id — every value it writes comes
    // from the tombstone the delete trigger captured, so the paper returns with
    // its original sharer, date, note and tags rather than being re-posted as
    // whoever happened to click undo.
    toast({
      message: `Removed from ${teamName}`,
      actionLabel: "Undo",
      onAction: async () => {
        const { error: undoErr } = await supabase.rpc("restore_post", { p_post: postId });
        refresh();
        // Throw rather than report: the toast keeps itself open and offers the
        // button again. A transient failure here used to consume the only Undo
        // there was, and the tombstone it leaves behind is reachable from no
        // other screen.
        if (undoErr) throw new Error(undoErr.message);
      },
    });
    onDeleted?.();
  }

  return (
    <div className="bg-danger/5 px-3.5 py-3">
      {error ? (
        <p className="text-xs text-danger">{error}</p>
      ) : (
        <>
          <p className="text-sm font-semibold text-fg">Remove from {teamName}?</p>
          {/* The consequence, and nothing else. A softening clause about what can
              be recovered belongs nowhere near the moment of commitment — it
              invites a faster yes to an action that affects other people. */}
          <p className="mt-1 text-xs leading-relaxed text-muted">
            Everyone in the lab will lose access to this paper.
          </p>
        </>
      )}
      {/* Sized to their labels and pushed right. The earlier awkwardness was
          Cancel looking like indented text, not the alignment itself — with a
          border and a fill it reads as a button, and a panel this narrow leaves
          no void worth closing. Cancel first, destructive last. */}
      <div className="mt-3 flex items-stretch justify-end gap-2">
        <button
          type="button"
          ref={cancelRef}
          onClick={onCancel}
          className={cn(
            "inline-flex h-9 items-center justify-center rounded-control px-3 text-xs font-medium",
            // border-strong and a solid fill: plain `border` is near-invisible
            // against the danger tint, which is what made this read as text.
            "border border-border-strong bg-surface text-fg transition hover:bg-surface-3",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          )}
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={del}
          disabled={busy}
          className={cn(
            "inline-flex h-9 items-center justify-center rounded-control bg-danger px-3 text-xs font-semibold",
            // danger-fg, not white: white on the dark theme's #ef6a55 is 3.06:1,
            // under the 4.5:1 AA needs for text this size. The token flips per
            // theme (6.35:1 dark, 5.13:1 light).
            "text-danger-fg transition hover:brightness-110 disabled:opacity-60",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger",
          )}
        >
          {busy ? "Removing…" : "Remove for everyone"}
        </button>
      </div>
    </div>
  );
}

/** A long author list is four lines of noise on open. Show the first few and let
 *  the reader expand the rest — mirroring the table view's truncation. */
function AuthorList({ authors }: { authors: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const LEAD = 5;
  const hidden = authors.length - LEAD;
  // Hiding a single author would trade one name for a longer "+1 more" button.
  const shown = expanded || hidden <= 1 ? authors : authors.slice(0, LEAD);
  return (
    <div className="mt-2.5 text-sm text-muted">
      {shown.join(", ")}
      {!expanded && hidden > 1 && (
        <>
          {" "}
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="font-medium text-accent hover:underline"
          >
            +{hidden} more
          </button>
        </>
      )}
    </div>
  );
}

/** The paper's canonical identifier, as a link rather than dead text: a labelled,
 *  clickable DOI where we can find one (resolved through doi.org), otherwise the
 *  source host — never a bare, unclickable URL that reads as a broken fragment. */
function PaperIdentifier({ doi, url }: { doi: string | null; url: string | null }) {
  // bareDoi is the normaliser the BibTeX/RIS/CSV exporters already use, and it
  // covers the forms our sources store (www., scheme-less, "doi: " with a
  // space). A third, weaker copy here made Cite and this link disagree about
  // the same paper's DOI.
  const bare = doi ? bareDoi(doi) : null;
  // Anchored to the path and stopped at ?/#: unanchored \S+ swallowed query
  // strings into the href and matched hosts like "notdoi.org" that aren't the
  // resolver at all.
  const fromUrl = url?.match(/^https?:\/\/(?:www\.)?(?:dx\.)?doi\.org\/([^?#\s]+)/i)?.[1] ?? null;
  const id = bare || fromUrl || null;
  let host: string | null = null;
  try {
    host = url ? new URL(url).host.replace(/^www\./, "") : null;
  } catch {
    host = null;
  }
  const href = id ? `https://doi.org/${encodeURI(id)}` : safeHref(url);
  const label = id ? `DOI ${id}` : host;
  if (!href || !label) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="mt-1 inline-block break-all font-mono text-xs text-faint underline-offset-2 transition hover:text-accent hover:underline"
    >
      {label}
    </a>
  );
}

const CITE_FORMATS: ExportFormat[] = ["bibtex", "ris", "markdown", "text", "csv"];

/** Copy or download a single paper as a citation, in any export format. Grabbing
 *  one BibTeX entry otherwise means entering the multi-select bar and selecting a
 *  single card; this puts it on the paper itself.
 *
 *  Same shape as ExportBar's menu — pick a format, then an explicit Copy or
 *  Download. The formats used to BE the buttons, which read as a list of labels:
 *  nothing told you that clicking one would copy, and the only confirmation was
 *  a checkmark that showed for a second and a half. */
function CitePaperButton({ paper }: { paper: ExportPaper }) {
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<ExportFormat>("bibtex");
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);
  useDismissable(ref, open, () => setOpen(false));

  // Drop the confirmation when the format changes, so "Copied" never sits beside
  // a format other than the one actually on the clipboard.
  useEffect(() => setCopied(false), [format]);

  const text = () => formatPapers([paper], format);

  function download() {
    downloadText(exportFilename(format, 1), text(), FORMAT_META[format].mime);
    setOpen(false);
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text());
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard blocked (insecure context, denied permission) — fall back to a
      // download so the citation is still obtainable.
      download();
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(ACTION_BTN, GHOST_BTN, open && "bg-surface-2 text-fg")}
      >
        <Quote size={13} /> Cite
      </button>
      {open && (
        <div className={POPOVER}>
          <div className="border-b border-border px-4 py-2.5 text-eyebrow font-semibold uppercase tracking-eyebrow text-faint">
            Cite this paper
          </div>

          <div role="radiogroup" aria-label="Citation format" className="flex flex-col p-1.5">
            {CITE_FORMATS.map((f) => (
              <button
                key={f}
                type="button"
                role="radio"
                aria-checked={format === f}
                onClick={() => setFormat(f)}
                className={cn(
                  "flex items-center gap-3 rounded-control px-2.5 py-2 text-left transition hover:bg-surface-2",
                  format === f && "bg-surface-2",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "grid h-4 w-4 shrink-0 place-items-center rounded-full border",
                    format === f ? "border-accent" : "border-border-strong",
                  )}
                >
                  {format === f && <span className="h-2 w-2 rounded-full bg-accent" />}
                </span>
                <span className="text-sm font-medium text-fg">{FORMAT_META[f].label}</span>
              </button>
            ))}
          </div>

          <div className="flex gap-1.5 border-t border-border p-1.5">
            <button
              type="button"
              onClick={copy}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-control px-3 py-2 text-sm font-medium text-fg transition hover:bg-surface-2"
            >
              {copied ? (
                <>
                  <Check size={14} className="text-accent" /> Copied
                </>
              ) : (
                <>
                  <Copy size={14} /> Copy
                </>
              )}
            </button>
            <button
              type="button"
              onClick={download}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-control bg-accent px-3 py-2 text-sm font-medium text-accent-fg transition hover:brightness-110"
            >
              <Download size={14} /> Download
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** The lab's most similar papers by embedding (hidden until embeddings exist). */
function SimilarPapers({
  paperId,
  teamId,
  fullPage = false,
}: {
  paperId: string;
  teamId: string;
  /** On /papers/:id, follow the link as a route rather than stacking a modal
   *  on top of the page — PaperModalProvider wraps the Outlet, so the hook
   *  resolves here too and would otherwise open ?paper=B at the URL /papers/A. */
  fullPage?: boolean;
}) {
  const { openPaper } = usePaperModal();
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ["similar-papers", teamId, paperId],
    queryFn: async (): Promise<SimilarPaper[]> => {
      const { data, error } = await supabase.rpc("similar_papers", {
        p_team: teamId,
        p_paper: paperId,
      });
      if (error) throw error;
      return (data ?? []) as SimilarPaper[];
    },
  });

  const similar = data ?? [];
  if (similar.length === 0) return null;

  return (
    <>
      <MetaLabel>Similar papers</MetaLabel>
      <ul className="flex flex-col gap-0.5">
        {similar.map((s) => (
          <li key={s.paper_id}>
            <button
              type="button"
              onClick={() =>
                fullPage ? navigate(`/papers/${s.paper_id}`) : openPaper(s.paper_id)
              }
              className="w-full rounded-control px-2 py-1.5 text-left text-sm transition hover:bg-surface-2"
            >
              <span className="text-fg">{s.title ?? "Untitled"}</span>
              {[s.venue, s.year].filter(Boolean).length > 0 && (
                <span className="ml-2 font-mono text-xs text-faint">
                  {[s.venue, s.year].filter(Boolean).join(" · ")}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

function MarkReadButton({
  paperId,
  teamId,
  userId,
}: {
  paperId: string;
  teamId: string;
  userId: string;
}) {
  const qc = useQueryClient();
  const { data: readSet } = useReadPapers(userId, teamId);
  const isRead = readSet?.has(paperId) ?? false;
  const [busy, setBusy] = useState(false);

  // Toggle read ↔ unread on the progress axis ONLY. This used to delete the
  // whole row to mean "unread", which threw away the save with it, and the
  // upsert used to overwrite `to_read` with `read`, which silently un-saved the
  // paper. Both axes now survive each other.
  async function toggle() {
    if (busy) return;
    setBusy(true);
    const { error } = await supabase
      .from("paper_status")
      .upsert(
        { user_id: userId, team_id: teamId, paper_id: paperId, status: isRead ? "unread" : "read" },
        { onConflict: "user_id,paper_id,team_id" },
      );
    setBusy(false);
    if (!error) {
      await qc.invalidateQueries({ queryKey: ["reading-list"] });
      await qc.invalidateQueries({ queryKey: ["read-papers"] });
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      aria-pressed={isRead}
      // The visible label is the STATE ("Read"), which is ambiguous read aloud,
      // so the accessible name carries the action instead — the same split
      // BookmarkButton uses for "Saved" / "Remove from reading list".
      aria-label={isRead ? "Mark as unread" : "Mark as read"}
      title={isRead ? "Mark as unread" : "Mark as read"}
      className={cn(
        // min-w, and the label never gets longer than it: the text used to grow
        // from "Mark read" to "Mark unread" (112px -> 129px) and shrink back,
        // which jumps the row under the pointer — and Safari does not repaint
        // the strip the button vacates, leaving a dark sliver beside it.
        ACTION_BTN,
        "min-w-[7rem] justify-center border font-medium disabled:opacity-60",
        isRead
          ? "border-accent bg-accent-weak text-accent"
          : "border-border hover:border-accent hover:text-accent",
      )}
    >
      {/* State, not instruction — the same way the bookmark beside it reads
          "Save" then "Saved". The action lives in the title and aria-pressed. */}
      <Check size={14} /> {isRead ? "Read" : "Mark read"}
    </button>
  );
}

function MetaLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-2 mt-5 text-eyebrow font-bold uppercase tracking-eyebrow text-muted">{children}</div>
  );
}

function LinkBtn({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-2 text-sm font-medium transition hover:border-accent hover:text-accent"
    >
      {children} <ExternalLink size={13} />
    </a>
  );
}

/** Lab-scoped, editable tags on the post. Canonical (paper/keyword) tags render
 *  as dashed chips you can click to add. */
function PaperTags({
  postId,
  teamId,
  initial,
  canonical,
}: {
  postId: string;
  teamId: string;
  initial: string[];
  canonical: string[];
}) {
  const qc = useQueryClient();
  const [tags, setTags] = useState<string[]>(initial);
  const [input, setInput] = useState("");
  // As you type, offer the lab's existing tags first, so a variant of a tag the
  // lab already uses ("tumour-…" next to "tumor-…") is one click away from not
  // being created. The server does the matching (team_tags), so British typing
  // finds the American-spelled tags the database stores.
  const typed = normaliseTag(input);
  const q = useDebouncedValue(typed, 200);
  const { data: matches } = useQuery({
    queryKey: ["team-tags", teamId, "suggest", q],
    queryFn: () => loadTeamTags(teamId)(q, 10),
    enabled: q !== "",
    staleTime: 60 * 1000,
  });
  const suggestions = typed
    ? (matches ?? [])
        .map((o) => o.value)
        .filter((t) => t !== typed && !tags.includes(t))
        .slice(0, 6)
    : [];

  async function persist(next: string[]) {
    setTags(next);
    // The database's clean_tags trigger may re-spell what we sent (a merged tag
    // becomes the one kept), so show what it actually stored.
    const { data } = await supabase
      .from("paper_posts")
      .update({ tags: next })
      .eq("id", postId)
      .select("tags")
      .maybeSingle();
    if (data) setTags(data.tags as string[]);
    void qc.invalidateQueries({ queryKey: ["paper-search", teamId] });
    void qc.invalidateQueries({ queryKey: ["team-tags", teamId] });
    void qc.invalidateQueries({ queryKey: ["paper-post"] });
  }

  function add(e: FormEvent) {
    e.preventDefault();
    setInput("");
    if (typed && !tags.includes(typed)) void persist([...tags, typed]);
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tags.map((t) => (
        <span
          key={t}
          className="inline-flex items-center gap-1 rounded-chip border border-accent/40 bg-accent-weak px-2 py-0.5 font-mono text-xs text-accent"
        >
          {t}
          <button
            type="button"
            aria-label={`Remove ${t}`}
            onClick={() => void persist(tags.filter((x) => x !== t))}
            className="text-accent/70 hover:text-danger"
          >
            ×
          </button>
        </span>
      ))}
      {canonical
        .filter((t) => !tags.includes(t))
        .map((t) => (
          <button
            key={t}
            type="button"
            title="Add tag"
            onClick={() => void persist([...tags, t])}
            className="rounded-chip border border-dashed border-border px-2 py-0.5 font-mono text-xs text-faint transition hover:border-accent hover:text-accent"
          >
            {t}
          </button>
        ))}
      <form onSubmit={add}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="+ tag"
          aria-label="Add a tag"
          className="w-20 rounded-chip border border-border bg-surface px-2 py-0.5 font-mono text-xs placeholder:text-faint focus:w-40 focus:outline-none focus:ring-1 focus:ring-accent"
        />
      </form>
      {suggestions.length > 0 && (
        <div className="flex w-full flex-wrap items-center gap-1.5" aria-label="Existing tags">
          <span className="text-xs text-faint">In use:</span>
          {suggestions.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => {
                setInput("");
                void persist([...tags, t]);
              }}
              className="rounded-chip border border-dashed border-border px-2 py-0.5 font-mono text-xs text-muted transition hover:border-accent hover:text-accent"
            >
              {t}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
