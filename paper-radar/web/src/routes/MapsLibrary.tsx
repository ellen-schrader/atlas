import { type FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Loader2, Map as MapIcon, Plus, Trash2 } from "lucide-react";

import { createMap, deleteMap, fetchMaps } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

/**
 * The maps hub: the pinned whole-lab overview plus the lab's topic maps, and an
 * inline "new map" that lands you straight on the fresh dashboard. Maps are a
 * *collection* (an atlas), so this is a library, not a single page.
 */
export default function MapsLibrary() {
  const { team } = useAppContext();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: maps, isLoading } = useQuery({
    queryKey: ["maps", team.id],
    queryFn: () => fetchMaps(team.id),
  });

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
        <h1 className="font-serif text-display font-semibold tracking-tight text-fg">Maps</h1>
        <p className="mt-1.5 max-w-[64ch] text-sm text-muted">
          A topic map tracks a subject your lab cares about — a live t-SNE of its papers, the labs
          and sub-themes driving it, and (soon) a digest of what’s new. Start from the whole-lab
          overview, or make a focused one.
        </p>
      </header>

      <form onSubmit={submit} className="rounded-card border border-border bg-surface p-4">
        <h2 className="mb-2 text-sm font-semibold text-fg">New map</h2>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name — e.g. Ovarian Cancer"
            className="rounded-control border border-border bg-surface-2 px-3 py-2 text-sm text-fg outline-none focus:border-accent sm:w-56"
          />
          <input
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder="What’s it about? e.g. ovarian cancer, HGSOC, platinum resistance"
            className="flex-1 rounded-control border border-border bg-surface-2 px-3 py-2 text-sm text-fg outline-none focus:border-accent"
          />
          <button
            type="submit"
            disabled={!name.trim() || !seed.trim() || create.isPending}
            className="inline-flex items-center justify-center gap-1.5 rounded-control bg-accent px-3.5 py-2 text-sm font-semibold text-accent-fg transition hover:brightness-110 disabled:opacity-50"
          >
            {create.isPending ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
            Create
          </button>
        </div>
        <p className="mt-2 text-xs text-faint">
          Membership is a live semantic match on the seed, so the map stays current as papers are
          posted. Shared with {team.name} by default.
        </p>
        {create.isError && (
          <p className="mt-2 text-xs text-danger">{(create.error as Error).message}</p>
        )}
      </form>

      <div className="grid gap-3 sm:grid-cols-2">
        <Link
          to="/map"
          className="rounded-card border border-accent/40 bg-accent-weak p-4 transition hover:border-accent"
        >
          <div className="flex items-center gap-2 text-accent">
            <MapIcon size={16} />
            <span className="font-serif text-base font-semibold">Lab overview</span>
          </div>
          <p className="mt-1 text-sm text-muted">
            Every paper in {team.name}, mapped — the pinned whole-corpus view.
          </p>
        </Link>

        {isLoading && (
          <div className="h-[92px] animate-pulse rounded-card border border-border bg-surface" />
        )}

        {maps?.map((m) => (
          <Link
            key={m.id}
            to={`/maps/${m.id}`}
            className="group relative rounded-card border border-border bg-surface p-4 transition hover:border-border-strong"
          >
            <div className="font-serif text-base font-semibold text-fg">{m.name}</div>
            <p className="mt-0.5 line-clamp-2 text-sm text-muted">{m.seed}</p>
            <div className="mt-2 text-xs text-faint">
              {m.visibility === "lab" ? "Shared with lab" : "Only you"}
            </div>
            <button
              type="button"
              aria-label={`Delete ${m.name}`}
              onClick={(e) => {
                e.preventDefault();
                if (window.confirm(`Delete the map “${m.name}”?`)) del.mutate(m.id);
              }}
              className="absolute right-3 top-3 text-faint opacity-0 transition hover:text-danger group-hover:opacity-100"
            >
              <Trash2 size={14} />
            </button>
          </Link>
        ))}
      </div>

      {!isLoading && !maps?.length && (
        <p className={cn("text-sm text-faint")}>No topic maps yet — create your first one above.</p>
      )}
    </div>
  );
}
