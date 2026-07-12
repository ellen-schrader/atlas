import { type DragEvent, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Loader2 } from "lucide-react";

import { FigureFields } from "@/components/FigureFields";
import type { PickedPaper } from "@/components/PaperPicker";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { uploadFigure } from "@/hooks/useFigures";
import { ACCEPTED_MIME, MAX_FILE_BYTES } from "@/lib/figures";
import { cn } from "@/lib/utils";

/** Upload a figure to the lab's mood board: pick/drop an image, give it a title,
 *  caption, category, and optionally link a paper. Validates format + size before
 *  upload; the hook reads natural dimensions and handles storage + row insert. */
export function FigureUploadDialog({
  open,
  onClose,
  teamId,
  userId,
}: {
  open: boolean;
  onClose: () => void;
  teamId: string;
  userId: string;
}) {
  const qc = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [caption, setCaption] = useState("");
  const [category, setCategory] = useState<string>("");
  const [paper, setPaper] = useState<PickedPaper | null>(null);
  const [origin, setOrigin] = useState<"own" | "third_party">("own");
  const [sourceUrl, setSourceUrl] = useState("");
  const [license, setLicense] = useState("");
  const [attribution, setAttribution] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Object-URL preview, revoked when the file changes or the dialog unmounts.
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function reset() {
    setFile(null);
    setTitle("");
    setCaption("");
    setCategory("");
    setPaper(null);
    setOrigin("own");
    setSourceUrl("");
    setLicense("");
    setAttribution("");
    setError(null);
    setBusy(false);
  }

  function close() {
    reset();
    onClose();
  }

  function pick(f: File | undefined) {
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
    setFile(f);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    pick(e.dataTransfer.files?.[0]);
  }

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await uploadFigure({
        file,
        teamId,
        userId,
        title,
        caption,
        category,
        paperId: paper?.id ?? null,
        origin,
        sourceUrl,
        license,
        attribution,
      });
      await qc.invalidateQueries({ queryKey: ["figures", teamId] });
      await qc.invalidateQueries({ queryKey: ["figure-categories", teamId] });
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={close} label="Upload a figure">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-6">
        <h2 className="text-[19px] font-bold tracking-tight">Upload a figure</h2>

        <input
          ref={fileInput}
          type="file"
          accept={ACCEPTED_MIME.join(",")}
          className="hidden"
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = ""; // allow re-selecting the same file later
          }}
        />

        {/* Drop zone / preview */}
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={onDrop}
          className={cn(
            "mt-4 w-full overflow-hidden rounded-card border text-center transition",
            previewUrl
              ? "border-border"
              : "border-2 border-dashed border-border-strong bg-surface-2 px-6 py-10 hover:border-accent",
          )}
        >
          {previewUrl ? (
            <img src={previewUrl} alt="Preview" className="max-h-72 w-full object-contain" />
          ) : (
            <span className="flex flex-col items-center gap-2 text-muted">
              <span className="grid h-11 w-11 place-items-center rounded-xl bg-accent-weak text-accent">
                <ImagePlus size={22} />
              </span>
              <span className="text-sm">
                <span className="font-semibold text-fg">Choose an image</span> or drag it here
              </span>
              <span className="text-xs text-faint">PNG, JPEG, WebP or GIF · up to 10 MB</span>
            </span>
          )}
        </button>
        {previewUrl && (
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            className="mt-2 self-start text-xs font-medium text-muted hover:text-accent"
          >
            Replace image
          </button>
        )}

        <div className="mt-5 flex flex-col gap-4">
          <FigureFields
            teamId={teamId}
            title={title}
            onTitle={setTitle}
            caption={caption}
            onCaption={setCaption}
            category={category}
            onCategory={setCategory}
            paper={paper}
            onPaper={setPaper}
            origin={origin}
            onOrigin={setOrigin}
            sourceUrl={sourceUrl}
            onSourceUrl={setSourceUrl}
            license={license}
            onLicense={setLicense}
            attribution={attribution}
            onAttribution={setAttribution}
          />
        </div>

        {error && <p className="mt-4 text-sm text-danger">{error}</p>}

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={busy || !file}>
            {busy ? <Loader2 className="animate-spin" size={15} /> : null}
            {busy ? "Uploading…" : "Add to board"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
