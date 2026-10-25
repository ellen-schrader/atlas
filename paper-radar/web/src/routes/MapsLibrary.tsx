import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Loader2, Map as MapIcon, Plus, Trash2, X } from "lucide-react";

import { createMap, deleteMap, fetchMaps } from "@/lib/api";
import type { MapDoc } from "@/lib/types";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useMyRole } from "@/hooks/useMyRole";
import { useAppContext } from "@/routes/Layout";

/**
 * The maps hub: the pinned whole-lab overview plus the lab's topic maps, each card
 * carrying its paper count and owner so you can tell them apart at a glance. The
 * "New map" form is a tile that expands on click, keeping the grid the focus.
 */
export default function MapsLibrary() {
  const { team, userId } = useAppContext();
  const { data: role } = useMyRole(team.id, userId);
  useDocumentTitle("Topic maps");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: maps, isLoading } = useQuery({
    queryKey: ["maps", team.id],
    queryFn: () => fetchMaps(team.id),
  });

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [seed, setSeed] = useState("");
  const create = useMutation({
    mutationFn: () => createMap(team.id, name.trim(), seed.trim()),
    onSuccess: (m) => {
      qc.invalidateQueries({ queryKey: ["maps", team.id] });
      navigate(`/maps/${m.id}`);
    },
  });
  const del = useMutation({
    mutationFn: (id: string) => deleteMap(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["maps", team.id] }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (name.trim() && seed.trim() && !create.isPending) create.mutate();
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-8">
      <header>
        <h1 className="text-display font-bold tracking-tight text-fg">Topic maps</h1>
        <p className="mt-1.5 max-w-[64ch] text-sm text-muted">
          Follow a topic your lab cares about: its papers, the groups publishing on it, and what’s
          new.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        <Link
          to="/maps/overview"
          className="rounded-card border border-accent/40 bg-accent-weak p-4 transition hover:border-accent"
        >
          <div className="flex items-center gap-2 text-accent">
            <MapIcon size={16} />
            <span className="text-base font-semibold">Lab overview</span>
          </div>
          <p className="mt-1 text-sm text-muted">
            All of {team.name}’s papers on one map.
          </p>
        </Link>

        {isLoading && (
          <div className="h-[104px] animate-pulse rounded-card border border-border bg-surface" />
        )}

        {maps?.map((m) => (
          <MapCard
            key={m.id}
            m={m}
            teamName={team.name}
            // A lab owner may also remove a map whose creator has left (RLS: maps_delete_orphan).
            canDelete={m.created_by === userId || (m.created_by === null && role === "owner")}
            onDelete={() => {
              if (window.confirm(`Delete the map “${m.name}”?`)) del.mutate(m.id);
            }}
          />
        ))}

        {/* New-map tile: expands into the form in place. */}
        {creating ? (
          <form onSubmit={submit} className="rounded-card border border-accent/50 bg-surface p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold text-fg">New map</span>
              <button type="button" onClick={() => setCreating(false)} aria-label="Cancel">
                <X size={14} className="text-muted hover:text-fg" />
              </button>
            </div>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name, e.g. Ovarian cancer"
              className="mb-2 w-full rounded-control border border-border bg-surface-2 px-3 py-2 text-sm text-fg outline-none focus:border-accent"
            />
            <input
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder="What’s it about? e.g. ovarian cancer, HGSOC, platinum resistance"
              className="mb-2 w-full rounded-control border border-border bg-surface-2 px-3 py-2 text-sm text-fg outline-none focus:border-accent"
            />
            <button
              type="submit"
              disabled={!name.trim() || !seed.trim() || create.isPending}
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-control bg-accent px-3.5 py-2 text-sm font-semibold text-accent-fg transition hover:brightness-110 disabled:opacity-50"
            >
              {create.isPending ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
              Create
            </button>
            {create.isError && (
              <p className="mt-2 text-xs text-danger">{(create.error as Error).message}</p>
            )}
          </form>
        ) : (
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="flex min-h-[104px] flex-col items-center justify-center gap-1 rounded-card border border-dashed border-border-strong text-sm font-medium text-muted transition hover:border-accent hover:text-accent"
          >
            <Plus size={18} /> New map
          </button>
        )}
      </div>

      <p className="text-xs text-faint">
        Maps update as your lab adds papers. They’re shared with {team.name} unless you make them
        private.
      </p>

      {del.isError && (
        <p className="text-sm text-danger">
          Couldn’t delete that map. {(del.error as Error).message}
        </p>
      )}
    </div>
  );
}

function MapCard({
  m,
  teamName,
  canDelete,
  onDelete,
}: {
  m: MapDoc;
  teamName: string;
  canDelete: boolean;
  onDelete: () => void;
}) {
  const count = m.paper_count ?? 0;
  const shared = m.visibility === "lab";
  const visibility = shared ? `Shared with ${teamName}` : "Only you";
  return (
    <Link
      to={`/maps/${m.id}`}
      className="group relative flex min-h-[104px] flex-col rounded-card border border-border bg-surface p-4 transition hover:border-border-strong"
    >
      <div className="text-base font-semibold text-fg">{m.name}</div>
      <p className="mt-0.5 line-clamp-2 text-sm text-muted">{m.seed}</p>
      <div className="mt-auto flex items-center gap-2 pt-2 text-xs text-faint">
        <span className="font-medium text-muted">
          {count} paper{count === 1 ? "" : "s"}
        </span>
        <span>·</span>
        <span className="truncate">{visibility}</span>
      </div>
      {shared && m.owner_name && (
        <p className="mt-0.5 truncate text-xs text-faint">by {m.owner_name}</p>
      )}
      {canDelete && (
        <button
          type="button"
          aria-label={`Delete ${m.name}`}
          onClick={(e) => {
            e.preventDefault();
            onDelete();
          }}
          className="absolute right-3 top-3 text-faint opacity-0 transition hover:text-danger group-hover:opacity-100"
        >
          <Trash2 size={14} />
        </button>
      )}
    </Link>
  );
}
