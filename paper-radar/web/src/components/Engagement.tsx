import { type FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Avatar } from "@/components/Avatar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useMembers } from "@/hooks/useMembers";
import { supabase } from "@/lib/supabase";
import { cn, formatDate, formatRelative } from "@/lib/utils";

const EMOJIS = ["👍", "❤️", "🎉", "💡", "🤔"];

interface ReactionRow {
  emoji: string;
  user_id: string;
}
interface CommentRow {
  id: string;
  body: string;
  created_at: string;
  author_id: string;
  profiles: { display_name: string } | null;
}
interface MemberRow {
  user_id: string;
  profiles: { display_name: string } | null;
}

/** What differs between engaging with a paper and engaging with a figure: the
 *  backing tables, the foreign-key column, whether @-mentions apply, and which
 *  card/list count query to refresh. Everything else is identical, so the two
 *  public entry points below are thin wrappers over one `Engagement`. */
type SubjectKind = "paper" | "figure";
interface SubjectConfig {
  commentsTable: string;
  reactionsTable: string;
  fk: string;
  supportsMentions: boolean;
  countsKey: string;
}
const SUBJECTS: Record<SubjectKind, SubjectConfig> = {
  paper: {
    commentsTable: "comments",
    reactionsTable: "reactions",
    fk: "paper_id",
    supportsMentions: true,
    countsKey: "engagement-counts",
  },
  figure: {
    commentsTable: "figure_comments",
    reactionsTable: "figure_reactions",
    fk: "figure_id",
    supportsMentions: false,
    countsKey: "figure-engagement-counts",
  },
};

interface Ctx {
  kind: SubjectKind;
  subjectId: string;
  teamId: string;
  userId: string;
}

/** Reactions + comments on a paper. Public API unchanged. */
export function PaperEngagement({
  paperId,
  teamId,
  userId,
}: {
  paperId: string;
  teamId: string;
  userId: string;
}) {
  return <Engagement kind="paper" subjectId={paperId} teamId={teamId} userId={userId} />;
}

/** Reactions + comments on a mood-board figure (no @-mentions in v1). */
export function FigureEngagement({
  figureId,
  teamId,
  userId,
}: {
  figureId: string;
  teamId: string;
  userId: string;
}) {
  return <Engagement kind="figure" subjectId={figureId} teamId={teamId} userId={userId} />;
}

function Engagement(ctx: Ctx) {
  return (
    <div className="flex flex-col gap-5">
      <Reactions {...ctx} />
      <Comments {...ctx} />
    </div>
  );
}

function Reactions({ kind, subjectId, teamId, userId }: Ctx) {
  const cfg = SUBJECTS[kind];
  const qc = useQueryClient();
  const key = [cfg.reactionsTable, subjectId, teamId];
  const { data } = useQuery({
    queryKey: key,
    queryFn: async (): Promise<ReactionRow[]> => {
      const { data, error } = await supabase
        .from(cfg.reactionsTable)
        .select("emoji, user_id")
        .eq(cfg.fk, subjectId)
        .eq("team_id", teamId);
      if (error) throw error;
      return (data ?? []) as ReactionRow[];
    },
  });
  const rows = data ?? [];
  const { data: members } = useMembers(teamId);
  const nameOf = (uid: string) =>
    uid === userId ? "You" : members?.find((m) => m.user_id === uid)?.profiles?.display_name ?? "Someone";

  async function toggle(emoji: string) {
    const mine = rows.some((r) => r.emoji === emoji && r.user_id === userId);
    if (mine) {
      await supabase
        .from(cfg.reactionsTable)
        .delete()
        .eq(cfg.fk, subjectId)
        .eq("team_id", teamId)
        .eq("user_id", userId)
        .eq("emoji", emoji);
    } else {
      await supabase
        .from(cfg.reactionsTable)
        .insert({ [cfg.fk]: subjectId, team_id: teamId, user_id: userId, emoji });
    }
    await qc.invalidateQueries({ queryKey: key });
    // refresh the card/list engagement counts (they read a separate query)
    await qc.invalidateQueries({ queryKey: [cfg.countsKey] });
  }

  return (
    <div className="flex flex-wrap gap-2">
      {EMOJIS.map((e) => {
        const who = rows.filter((r) => r.emoji === e).map((r) => nameOf(r.user_id));
        const mine = rows.some((r) => r.emoji === e && r.user_id === userId);
        return (
          <button
            key={e}
            type="button"
            onClick={() => toggle(e)}
            title={who.length > 0 ? who.join(", ") : undefined}
            className={cn(
              "rounded-full border px-2.5 py-1 text-sm transition",
              mine ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:border-accent",
            )}
          >
            {e}
            {who.length > 0 && <span className="ml-1 font-mono text-xs">{who.length}</span>}
          </button>
        );
      })}
    </div>
  );
}

function Comments({ kind, subjectId, teamId, userId }: Ctx) {
  const cfg = SUBJECTS[kind];
  const qc = useQueryClient();
  const commentsKey = [cfg.commentsTable, subjectId, teamId];

  const { data: comments } = useQuery({
    queryKey: commentsKey,
    queryFn: async (): Promise<CommentRow[]> => {
      const { data, error } = await supabase
        .from(cfg.commentsTable)
        .select("id, body, created_at, author_id, profiles(display_name)")
        .eq(cfg.fk, subjectId)
        .eq("team_id", teamId)
        .order("created_at");
      if (error) throw error;
      return (data ?? []) as unknown as CommentRow[];
    },
  });

  const { data: members } = useQuery({
    queryKey: ["members", teamId],
    enabled: cfg.supportsMentions,
    queryFn: async (): Promise<MemberRow[]> => {
      const { data, error } = await supabase
        .from("team_members")
        .select("user_id, profiles(display_name)")
        .eq("team_id", teamId);
      if (error) throw error;
      return (data ?? []) as unknown as MemberRow[];
    },
  });

  const [body, setBody] = useState("");
  const [mentionIds, setMentionIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");

  const teammates = cfg.supportsMentions ? (members ?? []).filter((m) => m.user_id !== userId) : [];

  async function saveEdit(id: string) {
    setError(null);
    // .select() returns the updated rows — an empty result means the write
    // matched nothing (e.g. the comment-edit RLS policy isn't applied yet),
    // which would otherwise fail silently.
    const { data, error: err } = await supabase
      .from(cfg.commentsTable)
      .update({ body: editBody.trim() })
      .eq("id", id)
      .select("id");
    if (err) {
      setError(err.message);
      return;
    }
    if (!data || data.length === 0) {
      setError("Couldn’t save — the comment-edit permission isn’t applied. Run `supabase db push`.");
      return;
    }
    setEditingId(null);
    await qc.invalidateQueries({ queryKey: commentsKey });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const { data: inserted, error: insErr } = await supabase
        .from(cfg.commentsTable)
        .insert({ [cfg.fk]: subjectId, team_id: teamId, author_id: userId, body: body.trim() })
        .select("id")
        .single();
      if (insErr) throw insErr;

      if (cfg.supportsMentions && mentionIds.length > 0) {
        const { error: mErr } = await supabase.from("mentions").insert(
          mentionIds.map((uid) => ({
            paper_id: subjectId,
            team_id: teamId,
            mentioned_user: uid,
            mentioned_by: userId,
            comment_id: inserted.id,
          })),
        );
        if (mErr) throw mErr;
      }

      setBody("");
      setMentionIds([]);
      await qc.invalidateQueries({ queryKey: commentsKey });
      await qc.invalidateQueries({ queryKey: [cfg.countsKey] });
      if (cfg.supportsMentions) await qc.invalidateQueries({ queryKey: ["mentions"] });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const list = comments ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs font-medium uppercase tracking-wide text-muted">
        {list.length > 0 ? `${list.length} ${list.length === 1 ? "comment" : "comments"}` : "Comments"}
      </div>

      {list.map((c) => (
        <div key={c.id} className="flex gap-2.5">
          <Avatar name={c.profiles?.display_name ?? "?"} size={26} />
          <div className="min-w-0 flex-1">
            <div className="text-xs">
              <span className="font-semibold text-fg">{c.profiles?.display_name ?? "Someone"}</span>
              <span className="ml-2 font-mono text-muted" title={formatDate(c.created_at)}>
                {formatRelative(c.created_at)}
              </span>
            </div>
            {editingId === c.id ? (
              <div className="mt-1 flex flex-col gap-2">
                <Textarea rows={2} value={editBody} onChange={(e) => setEditBody(e.target.value)} />
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => saveEdit(c.id)} disabled={!editBody.trim()}>
                    Save
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                    Cancel
                  </Button>
                </div>
                {error && <p className="text-xs text-danger">{error}</p>}
              </div>
            ) : (
              <>
                <div className="mt-0.5 whitespace-pre-wrap text-sm">{c.body}</div>
                {c.author_id === userId && (
                  <button
                    type="button"
                    onClick={() => {
                      setEditingId(c.id);
                      setEditBody(c.body);
                    }}
                    className="mt-0.5 text-xs text-muted hover:text-accent"
                  >
                    Edit
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      ))}

      <form onSubmit={submit} className="flex flex-col gap-2">
        <Textarea
          rows={2}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder="Add a comment for your team…"
        />
        {teammates.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted">Notify:</span>
            {teammates.map((m) => {
              const on = mentionIds.includes(m.user_id);
              return (
                <button
                  key={m.user_id}
                  type="button"
                  onClick={() =>
                    setMentionIds((ids) =>
                      on ? ids.filter((x) => x !== m.user_id) : [...ids, m.user_id],
                    )
                  }
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-xs transition",
                    on ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:border-accent",
                  )}
                >
                  @{m.profiles?.display_name ?? "member"}
                </button>
              );
            })}
          </div>
        )}
        {error && <p className="text-xs text-danger">{error}</p>}
        <div>
          <Button type="submit" size="sm" disabled={busy || !body.trim()}>
            {busy ? "…" : "Post comment"}
          </Button>
        </div>
      </form>
    </div>
  );
}
