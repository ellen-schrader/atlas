import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { supabase } from "@/lib/supabase";
import type { Figure } from "@/lib/types";
import {
  ACCEPTED_MIME,
  FIGURES_BUCKET,
  MAX_FILE_BYTES,
  figureStoragePath,
  readImageSize,
} from "@/lib/figures";

export const FIGURES_PAGE_SIZE = 24;

const SELECT =
  "*, uploader:profiles!figures_uploaded_by_fkey(display_name), papers(id, title)";

export interface FigureFilters {
  category?: string | null;
  linkedOnly?: boolean;
}

/** Paginated feed of a lab's figures, newest first, with the uploader and any
 *  linked paper joined. Category / "linked to paper" filters are applied
 *  server-side so paging stays correct. */
export function useFigures(teamId: string, filters: FigureFilters = {}) {
  const { category = null, linkedOnly = false } = filters;
  return useInfiniteQuery({
    queryKey: ["figures", teamId, category, linkedOnly],
    initialPageParam: 0,
    queryFn: async ({ pageParam }): Promise<Figure[]> => {
      let q = supabase.from("figures").select(SELECT).eq("team_id", teamId);
      if (category) q = q.eq("category", category);
      if (linkedOnly) q = q.not("paper_id", "is", null);
      const { data, error } = await q
        // `id` is a stable tiebreaker so figures sharing a created_at can't be
        // duplicated or skipped across pages.
        .order("created_at", { ascending: false })
        .order("id", { ascending: false })
        .range(pageParam, pageParam + FIGURES_PAGE_SIZE - 1);
      if (error) throw error;
      return (data ?? []) as unknown as Figure[];
    },
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length < FIGURES_PAGE_SIZE ? undefined : allPages.length * FIGURES_PAGE_SIZE,
  });
}

/** A single figure by id (for the detail modal), uploader + linked paper joined. */
export function useFigure(figureId: string | null, teamId: string) {
  return useQuery({
    queryKey: ["figure", teamId, figureId],
    enabled: figureId !== null,
    queryFn: async (): Promise<Figure | null> => {
      const { data, error } = await supabase
        .from("figures")
        .select(SELECT)
        .eq("id", figureId!)
        .maybeSingle();
      if (error) throw error;
      return (data as unknown as Figure) ?? null;
    },
  });
}

/** Batched, cached signed URLs for a page of storage paths. The bucket is
 *  private, so this respects the storage RLS policy under the caller's JWT.
 *  URLs expire in 60 min; cached for 45 so long-lived tabs refetch before then. */
export function useFigureUrls(paths: string[]) {
  const key = [...paths].sort().join(",");
  return useQuery({
    queryKey: ["figure-urls", key],
    enabled: paths.length > 0,
    staleTime: 45 * 60 * 1000,
    // As infinite scroll appends figures the key grows; keep the prior map so
    // already-loaded images don't blank out while the larger batch re-signs.
    placeholderData: keepPreviousData,
    queryFn: async (): Promise<Record<string, string>> => {
      const { data, error } = await supabase.storage
        .from(FIGURES_BUCKET)
        .createSignedUrls(paths, 60 * 60);
      if (error) throw error;
      const map: Record<string, string> = {};
      for (const row of data ?? []) {
        if (row.signedUrl && row.path) map[row.path] = row.signedUrl;
      }
      return map;
    },
  });
}

/** The categories a lab has actually used, most-used first (figure_categories
 *  RPC). Feeds the board filter chips and the "existing categories" suggestions
 *  in the upload / edit chooser. */
export function useFigureCategories(teamId: string) {
  return useQuery({
    queryKey: ["figure-categories", teamId],
    queryFn: async (): Promise<{ category: string; n: number }[]> => {
      const { data, error } = await supabase.rpc("figure_categories", { p_team: teamId });
      if (error) throw error;
      return (data ?? []) as { category: string; n: number }[];
    },
  });
}

export interface FigureCounts {
  reactions: number;
  comments: number;
}

/** Reaction + comment counts for a page of figures, mirroring useEngagementCounts
 *  for papers. Two team-scoped `.in()` reads, tallied client-side. */
export function useFigureEngagementCounts(teamId: string, figureIds: string[]) {
  const key = [...figureIds].sort().join(",");
  return useQuery({
    queryKey: ["figure-engagement-counts", teamId, key],
    enabled: figureIds.length > 0,
    // Keep prior counts while the growing id set re-fetches, so cards don't flash 0.
    placeholderData: keepPreviousData,
    queryFn: async (): Promise<Record<string, FigureCounts>> => {
      const [rx, cm] = await Promise.all([
        supabase
          .from("figure_reactions")
          .select("figure_id")
          .eq("team_id", teamId)
          .in("figure_id", figureIds),
        supabase
          .from("figure_comments")
          .select("figure_id")
          .eq("team_id", teamId)
          .in("figure_id", figureIds),
      ]);
      if (rx.error) throw rx.error;
      if (cm.error) throw cm.error;

      const map: Record<string, FigureCounts> = {};
      for (const id of figureIds) map[id] = { reactions: 0, comments: 0 };
      for (const r of rx.data ?? []) map[r.figure_id] && map[r.figure_id].reactions++;
      for (const c of cm.data ?? []) map[c.figure_id] && map[c.figure_id].comments++;
      return map;
    },
  });
}

export interface Provenance {
  origin: "own" | "third_party";
  sourceUrl: string | null;
  license: string | null;
  attribution: string | null;
}

/** Third-party provenance is only stored for third-party figures; 'own' clears it. */
function provenanceColumns(p: Provenance) {
  const third = p.origin === "third_party";
  return {
    origin: p.origin,
    source_url: third ? p.sourceUrl?.trim() || null : null,
    license: third ? p.license?.trim() || null : null,
    attribution: third ? p.attribution?.trim() || null : null,
  };
}

export interface UploadFigureInput extends Provenance {
  file: File;
  teamId: string;
  userId: string;
  title: string;
  caption: string;
  category: string;
  paperId: string | null;
}

/** Client-side upload: validate → read natural dimensions → put the object into
 *  the private bucket → insert the row. If the row insert fails, best-effort
 *  removes the just-uploaded object so we don't leave an orphan. Returns the new
 *  figure id. Throws a user-facing Error on validation or backend failure. */
export async function uploadFigure(input: UploadFigureInput): Promise<string> {
  const { file, teamId, userId, title, caption, category, paperId } = input;

  if (!ACCEPTED_MIME.includes(file.type as (typeof ACCEPTED_MIME)[number])) {
    throw new Error("Unsupported format — use PNG, JPEG, WebP or GIF.");
  }
  if (file.size > MAX_FILE_BYTES) {
    throw new Error("That image is over the 10 MB limit.");
  }

  const { width, height } = await readImageSize(file);

  const figureId = crypto.randomUUID();
  const path = figureStoragePath(teamId, figureId, file.type);

  const up = await supabase.storage
    .from(FIGURES_BUCKET)
    .upload(path, file, { contentType: file.type, upsert: false });
  if (up.error) throw up.error;

  const { error: insErr } = await supabase.from("figures").insert({
    id: figureId,
    team_id: teamId,
    uploaded_by: userId,
    storage_path: path,
    title: title.trim(),
    caption: caption.trim(),
    category,
    paper_id: paperId,
    width,
    height,
    mime_type: file.type,
    file_size: file.size,
    ...provenanceColumns(input),
  });
  if (insErr) {
    // Roll back the orphaned object (delete policy allows the owner).
    await supabase.storage.from(FIGURES_BUCKET).remove([path]);
    throw insErr;
  }

  return figureId;
}

export interface UpdateFigureInput extends Provenance {
  figure: Pick<Figure, "id" | "team_id" | "storage_path">;
  title: string;
  caption: string;
  category: string;
  paperId: string | null;
  newFile?: File | null; // optional replacement image
}

/** Edit a figure's metadata (uploader-only, enforced by RLS). If `newFile` is
 *  given, the image is replaced too: the new object is uploaded and the row's
 *  storage/dimension fields updated; a differently-named old object is then
 *  removed. Throws a user-facing Error on validation failure or if the update
 *  matched no row (i.e. you don't own it). */
export async function updateFigure(input: UpdateFigureInput): Promise<void> {
  const { figure, title, caption, category, paperId, newFile } = input;

  const patch: Record<string, unknown> = {
    title: title.trim(),
    caption: caption.trim(),
    category,
    paper_id: paperId,
    ...provenanceColumns(input),
  };

  // A newly-uploaded object at a *different* path than the current one — tracked
  // so we can roll it back if the row update then fails (orphan cleanup), or
  // remove the superseded old object on success.
  let freshObjectPath: string | null = null;
  if (newFile) {
    if (!ACCEPTED_MIME.includes(newFile.type as (typeof ACCEPTED_MIME)[number])) {
      throw new Error("Unsupported format — use PNG, JPEG, WebP or GIF.");
    }
    if (newFile.size > MAX_FILE_BYTES) {
      throw new Error("That image is over the 10 MB limit.");
    }
    const { width, height } = await readImageSize(newFile);
    const newPath = figureStoragePath(figure.team_id, figure.id, newFile.type);
    // upsert so a same-extension replacement overwrites in place.
    const up = await supabase.storage
      .from(FIGURES_BUCKET)
      .upload(newPath, newFile, { contentType: newFile.type, upsert: true });
    if (up.error) throw up.error;
    patch.storage_path = newPath;
    patch.width = width;
    patch.height = height;
    patch.mime_type = newFile.type;
    patch.file_size = newFile.size;
    if (newPath !== figure.storage_path) freshObjectPath = newPath;
  }

  // .select() so an empty result (RLS filtered the row out) surfaces as an error
  // instead of a silent no-op.
  const { data, error } = await supabase
    .from("figures")
    .update(patch)
    .eq("id", figure.id)
    .select("id");
  if (error || !data || data.length === 0) {
    // Roll back the orphaned new object (nothing points at it).
    if (freshObjectPath) await supabase.storage.from(FIGURES_BUCKET).remove([freshObjectPath]);
    if (error) throw error;
    throw new Error("Couldn’t save — you can only edit figures you posted.");
  }

  // Success: drop the superseded old object (only when it was renamed away).
  if (freshObjectPath) await supabase.storage.from(FIGURES_BUCKET).remove([figure.storage_path]);
}

/** Delete a figure the current user uploaded: remove the row (comments/reactions
 *  cascade) and its storage object. */
export async function deleteFigure(figure: Pick<Figure, "id" | "storage_path">): Promise<void> {
  const { error } = await supabase.from("figures").delete().eq("id", figure.id);
  if (error) throw error;
  await supabase.storage.from(FIGURES_BUCKET).remove([figure.storage_path]);
}
