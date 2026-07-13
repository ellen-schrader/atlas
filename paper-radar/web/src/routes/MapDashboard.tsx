import { type ReactNode, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";

import { fetchMapOverview, isTransientApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";
import { Scatter } from "@/routes/Map";

/**
 * A topic map's dashboard (Milestone 2): the scoped t-SNE + sub-themes over just
 * the map's member papers, under an identity header. The ranked paper list, key
 * labs, and AI summary land in the next milestones.
 */
export default function MapDashboard() {
  const { mapId } = useParams<{ mapId: string }>();
  const { team } = useAppContext();
  const [activeCluster, setActiveCluster] = useState<number | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["map-overview", mapId],
    queryFn: () => fetchMapOverview(mapId!),
    enabled: !!mapId,
    retry: (n, e) => isTransientApiError(e) && n < 5,
  });

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5 p-8">
      <Link to="/maps" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
        <ArrowLeft size={14} /> Maps
      </Link>

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted">
          <Loader2 size={16} className="animate-spin" /> Mapping this topic…
        </div>
      )}
      {error && <p className="text-sm text-danger">{(error as Error).message}</p>}

      {data && (
        <>
          <header>
            <p className="text-xs font-semibold uppercase tracking-wide text-accent">Topic map</p>
            <h1 className="font-serif text-display font-semibold tracking-tight text-fg">
              {data.name}
            </h1>
            <p className="mt-1 text-sm text-muted">
              papers near <span className="font-serif italic text-fg">{data.seed}</span>
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <Chip>
                {data.total} paper{data.total === 1 ? "" : "s"}
              </Chip>
              {data.new_this_week > 0 && <Chip accent>+{data.new_this_week} this week</Chip>}
              <Chip>{data.visibility === "lab" ? `Shared with ${team.name}` : "Only you"}</Chip>
            </div>
          </header>

          {data.points.length >= 2 ? (
            <section className="rounded-card border border-border bg-surface p-5">
              <h2 className="mb-1 font-serif text-lg font-semibold tracking-tight">The map</h2>
              <p className="mb-3 text-xs text-faint">
                {data.embedded} papers · {data.clusters.length} sub-theme
                {data.clusters.length === 1 ? "" : "s"} · t-SNE of embeddings
              </p>
              <Scatter
                points={data.points}
                clusters={data.clusters}
                colorBy="cluster"
                sizeBy="engagement"
                showHulls
                sims={null}
                labFilter={null}
                tagFilter={null}
                activeCluster={activeCluster}
                setActiveCluster={setActiveCluster}
                barHover={null}
              />
            </section>
          ) : (
            <div className="rounded-card border border-dashed border-border p-8 text-center text-sm text-faint">
              {data.total === 0
                ? "No papers match this topic yet. As the lab posts more, they’ll appear here."
                : "Only a paper or two here so far — too few to map. Broaden the seed, or add more papers to the lab."}
            </div>
          )}

          <p className="text-xs text-faint">
            Coming next: a ranked, searchable paper list (with an “unread” filter), the labs driving
            this topic, and an AI summary of recent developments.
          </p>
        </>
      )}
    </div>
  );
}

function Chip({ children, accent }: { children: ReactNode; accent?: boolean }) {
  return (
    <span
      className={cn(
        "rounded-chip border px-2 py-0.5",
        accent
          ? "border-accent/40 bg-accent-weak font-semibold text-accent"
          : "border-border bg-surface text-muted",
      )}
    >
      {children}
    </span>
  );
}
