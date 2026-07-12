import { type ReactNode, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileText, ImagePlus, Loader2, Pencil, Trash2 } from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { FigureEngagement } from "@/components/Engagement";
import { FigureFields } from "@/components/FigureFields";
import type { PickedPaper } from "@/components/PaperPicker";
import { usePaperModal } from "@/components/PaperModal";
import { Button } from "@/components/ui/button";
import { deleteFigure, updateFigure, useFigureUrls } from "@/hooks/useFigures";
import { ACCEPTED_MIME, MAX_FILE_BYTES, aspectRatio, categoryLabel } from "@/lib/figures";
import type { Figure } from "@/lib/types";
import { formatDate } from "@/lib/utils";

/** Full detail for a figure: the image large, its category + caption, uploader,
 *  a linked-paper chip that swaps to the paper modal, and the shared
 *  reactions/comments engagement. The uploader also gets inline edit (title,
 *  caption, category, linked paper, and image replacement) and delete. */
export function FigureDetail({
  figure,
  teamId,
  userId,
  onClose,
}: {
  figure: Figure;
  teamId: string;
  userId: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const { openPaper } = usePaperModal();
  const { data: urls } = useFigureUrls([figure.storage_path]);
  const url = urls?.[figure.storage_path];

  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const uploaderName = figure.uploader?.display_name ?? null;
  const isOwner = figure.uploaded_by === userId;

  function openLinkedPaper() {
    if (!figure.paper_id) return;
    onClose(); // clear ?figure= …
    openPaper(figure.paper_id); // …and set ?paper=
  }

  async function invalidate() {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ["figures", teamId] }),
      qc.invalidateQueries({ queryKey: ["figure", teamId, figure.id] }),
      qc.invalidateQueries({ queryKey: ["figure-urls"] }),
      qc.invalidateQueries({ queryKey: ["figure-categories", teamId] }),
    ]);
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await deleteFigure(figure);
      await qc.invalidateQueries({ queryKey: ["figures", teamId] });
      await qc.invalidateQueries({ queryKey: ["figure-categories", teamId] });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        className="grid max-h-[46vh] shrink-0 place-items-center overflow-hidden border-b border-border bg-surface-2 p-5"
        style={{ aspectRatio: url ? undefined : aspectRatio(figure) }}
      >
        {url ? (
          <img
            src={url}
            alt={figure.title || figure.caption || "Figure"}
            className="max-h-[42vh] w-auto max-w-full rounded-md object-contain shadow-sm"
          />
        ) : (
          <Loader2 className="animate-spin text-muted" size={20} />
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {editing ? (
          <FigureEditForm
            figure={figure}
            currentUrl={url}
            onCancel={() => setEditing(false)}
            onSaved={async () => {
              await invalidate();
              setEditing(false);
            }}
          />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2.5">
              {figure.category.trim() && (
                <span className="rounded-full border border-accent/40 bg-accent-weak px-2.5 py-0.5 text-eyebrow font-semibold uppercase tracking-eyebrow text-accent">
                  {categoryLabel(figure.category)}
                </span>
              )}
              <span className="inline-flex items-center gap-2 text-xs text-muted">
                {uploaderName && <Avatar name={uploaderName} size={20} />}
                <span>
                  {uploaderName ? `${uploaderName} · ` : ""}
                  <span className="tabular-nums">{formatDate(figure.created_at)}</span>
                </span>
              </span>
              {isOwner && (
                <button
                  type="button"
                  onClick={() => {
                    setError(null);
                    setEditing(true);
                  }}
                  className="ml-auto inline-flex items-center gap-1.5 rounded-control border border-border px-2.5 py-1 text-xs font-medium text-muted transition hover:border-accent hover:text-accent"
                >
                  <Pencil size={13} /> Edit
                </button>
              )}
            </div>

            {figure.title && (
              <h2 className="mt-3 text-balance text-[21px] font-bold leading-tight tracking-tight">
                {figure.title}
              </h2>
            )}
            {figure.caption && (
              <p className="mt-2 text-sm leading-relaxed text-fg/90">{figure.caption}</p>
            )}

            {figure.papers && (
              <button
                type="button"
                onClick={openLinkedPaper}
                className="mt-4 flex w-full items-center gap-3 rounded-control border border-border bg-surface-2 p-3 text-left transition hover:border-accent hover:bg-accent-weak"
              >
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-accent-weak text-accent">
                  <FileText size={18} />
                </span>
                <span className="min-w-0">
                  <span className="block text-eyebrow font-bold uppercase tracking-eyebrow text-muted">
                    Linked paper
                  </span>
                  <span className="block truncate text-sm font-semibold text-fg">
                    {figure.papers.title ?? "Open paper"}
                  </span>
                </span>
                <span className="ml-auto shrink-0 text-xs font-semibold text-accent">Open →</span>
              </button>
            )}

            <hr className="my-6 border-border" />
            <MetaLabel>Discussion</MetaLabel>
            <FigureEngagement figureId={figure.id} teamId={teamId} userId={userId} />

            {isOwner && (
              <>
                <hr className="my-6 border-border" />
                {confirm ? (
                  <div className="flex flex-col gap-2 rounded-control border border-danger/40 bg-danger/5 p-3">
                    <span className="text-sm text-fg">
                      Delete this figure? Its comments and reactions go with it.
                    </span>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={remove}
                        disabled={busy}
                        className="inline-flex items-center gap-1.5 rounded-control bg-danger px-3 py-1.5 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-50"
                      >
                        {busy ? <Loader2 className="animate-spin" size={14} /> : <Trash2 size={14} />}
                        Delete
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirm(false)}
                        disabled={busy}
                        className="rounded-control px-3 py-1.5 text-sm text-muted hover:text-fg"
                      >
                        Cancel
                      </button>
                    </div>
                    {error && <p className="text-xs text-danger">{error}</p>}
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setConfirm(true)}
                    className="inline-flex items-center gap-1.5 text-sm text-muted transition hover:text-danger"
                  >
                    <Trash2 size={14} /> Delete figure
                  </button>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** The uploader's inline edit form: shared metadata fields plus an optional
 *  image replacement, saved via updateFigure. */
function FigureEditForm({
  figure,
  currentUrl,
  onCancel,
  onSaved,
}: {
  figure: Figure;
  currentUrl?: string;
  onCancel: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [title, setTitle] = useState(figure.title);
  const [caption, setCaption] = useState(figure.caption);
  const [category, setCategory] = useState(figure.category);
  const [paper, setPaper] = useState<PickedPaper | null>(
    figure.papers ? { id: figure.papers.id, title: figure.papers.title ?? "Linked paper" } : null,
  );
  const [newFile, setNewFile] = useState<File | null>(null);
  const [newPreview, setNewPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!newFile) {
      setNewPreview(null);
      return;
    }
    const u = URL.createObjectURL(newFile);
    setNewPreview(u);
    return () => URL.revokeObjectURL(u);
  }, [newFile]);

  function pickReplacement(f: File | undefined) {
    if (!f) return;
    setError(null);
    if (!ACCEPTED_MIME.includes(f.type as (typeof ACCEPTED_MIME)[number])) {
      setError("Unsupported format — use PNG, JPEG, WebP or GIF.");
      return;
    }
    if (f.size > MAX_FILE_BYTES) {
      setError("That image is over the 10 MB limit.");
      return;
    }
    setNewFile(f);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await updateFigure({
        figure,
        title,
        caption,
        category,
        paperId: paper?.id ?? null,
        newFile,
      });
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        {newPreview ?? currentUrl ? (
          <img
            src={newPreview ?? currentUrl}
            alt="Current figure"
            className="h-16 w-16 rounded-md border border-border object-cover"
          />
        ) : (
          <div className="grid h-16 w-16 place-items-center rounded-md border border-border bg-surface-2">
            <Loader2 className="animate-spin text-muted" size={16} />
          </div>
        )}
        <div>
          <input
            ref={fileInput}
            type="file"
            accept={ACCEPTED_MIME.join(",")}
            className="hidden"
            onChange={(e) => {
              pickReplacement(e.target.files?.[0]);
              e.target.value = ""; // allow re-selecting the same file later
            }}
          />
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            className="inline-flex items-center gap-1.5 rounded-control border border-border px-3 py-1.5 text-sm font-medium text-muted transition hover:border-accent hover:text-accent"
          >
            <ImagePlus size={14} /> {newFile ? "Change replacement" : "Replace image"}
          </button>
          {newFile && (
            <button
              type="button"
              onClick={() => setNewFile(null)}
              className="ml-2 text-xs text-muted hover:text-danger"
            >
              Keep original
            </button>
          )}
        </div>
      </div>

      <FigureFields
        teamId={figure.team_id}
        title={title}
        onTitle={setTitle}
        caption={caption}
        onCaption={setCaption}
        category={category}
        onCategory={setCategory}
        paper={paper}
        onPaper={setPaper}
      />

      {error && <p className="text-sm text-danger">{error}</p>}

      <div className="flex gap-2">
        <Button onClick={save} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" size={15} /> : null}
          {busy ? "Saving…" : "Save changes"}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function MetaLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-2 mt-5 text-eyebrow font-bold uppercase tracking-eyebrow text-muted">
      {children}
    </div>
  );
}
