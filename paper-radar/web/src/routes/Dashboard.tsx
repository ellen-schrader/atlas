import { useQuery, useQueryClient } from "@tanstack/react-query";

import { usePaperModal } from "@/components/PaperModal";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { usePapers } from "@/hooks/usePapers";
import { supabase } from "@/lib/supabase";
import { formatDate } from "@/lib/utils";
import { useAppContext } from "@/routes/Layout";

interface MentionRow {
  id: string;
  created_at: string;
  seen_at: string | null;
  paper_id: string;
  papers: { id: string; title: string | null } | null;
}
interface TbrRow {
  paper_id: string;
  updated_at: string;
  papers: { id: string; title: string | null; venue: string | null; year: number | null } | null;
}

export default function Dashboard() {
  const { team, userId, displayName } = useAppContext();
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <div>
        <h1 className="text-lg font-semibold">Welcome back, {displayName}</h1>
        <p className="text-sm text-muted">What needs your attention in {team.name}.</p>
      </div>
      <Mentions userId={userId} />
      <ToRead userId={userId} />
      <Recent teamId={team.id} />
    </div>
  );
}

function Mentions({ userId }: { userId: string }) {
  const qc = useQueryClient();
  const { openPaper } = usePaperModal();
  const key = ["mentions", userId];
  const { data } = useQuery({
    queryKey: key,
    queryFn: async (): Promise<MentionRow[]> => {
      const { data, error } = await supabase
        .from("mentions")
        .select("id, created_at, seen_at, paper_id, papers(id, title)")
        .eq("mentioned_user", userId)
        .order("created_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as unknown as MentionRow[];
    },
  });
  const rows = data ?? [];
  if (rows.length === 0) return null;

  async function markSeen(id: string) {
    await supabase.from("mentions").update({ seen_at: new Date().toISOString() }).eq("id", id);
    await qc.invalidateQueries({ queryKey: key });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Mentions</CardTitle>
        <CardDescription>Papers a teammate tagged you on.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col divide-y divide-border">
        {rows.map((m) => (
          <div key={m.id} className="flex items-center gap-3 py-2 first:pt-0 last:pb-0">
            <span
              className={`h-2 w-2 shrink-0 rounded-full ${m.seen_at ? "bg-transparent" : "bg-accent"}`}
            />
            <button
              onClick={() => openPaper(m.paper_id)}
              className="flex-1 truncate text-left text-sm hover:text-accent"
            >
              {m.papers?.title ?? "A paper"}
            </button>
            <span className="font-mono text-xs text-muted">{formatDate(m.created_at)}</span>
            {!m.seen_at && (
              <button onClick={() => markSeen(m.id)} className="text-xs text-muted hover:text-accent">
                Mark read
              </button>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function ToRead({ userId }: { userId: string }) {
  const { openPaper } = usePaperModal();
  const { data } = useQuery({
    queryKey: ["tbr", userId],
    queryFn: async (): Promise<TbrRow[]> => {
      const { data, error } = await supabase
        .from("paper_status")
        .select("paper_id, updated_at, papers(id, title, venue, year)")
        .eq("user_id", userId)
        .eq("status", "to_read")
        .order("updated_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as unknown as TbrRow[];
    },
  });
  const rows = data ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>To read</CardTitle>
        <CardDescription>Your reading list.</CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted">Nothing queued — papers you’re mentioned on land here.</p>
        ) : (
          <div className="flex flex-col divide-y divide-border">
            {rows.map((r) => (
              <button
                key={r.paper_id}
                onClick={() => openPaper(r.paper_id)}
                className="flex items-center justify-between gap-3 py-2 text-left first:pt-0 last:pb-0 hover:text-accent"
              >
                <span className="truncate text-sm">{r.papers?.title ?? "A paper"}</span>
                <span className="shrink-0 font-mono text-xs text-muted">
                  {[r.papers?.venue, r.papers?.year].filter(Boolean).join(" · ")}
                </span>
              </button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Recent({ teamId }: { teamId: string }) {
  const { openPaper } = usePaperModal();
  const { data } = usePapers(teamId);
  const rows = (data ?? []).slice(0, 6);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recently posted</CardTitle>
        <CardDescription>Newest in your lab.</CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted">No papers yet.</p>
        ) : (
          <div className="flex flex-col divide-y divide-border">
            {rows.map((p) => (
              <button
                key={p.id}
                onClick={() => openPaper(p.papers.id)}
                className="flex items-center justify-between gap-3 py-2 text-left first:pt-0 last:pb-0 hover:text-accent"
              >
                <span className="truncate text-sm">{p.papers.title ?? p.papers.url}</span>
                <span className="shrink-0 font-mono text-xs text-muted">{formatDate(p.posted_at)}</span>
              </button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
