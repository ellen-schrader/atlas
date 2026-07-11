import { type FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Avatar } from "@/components/Avatar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { supabase } from "@/lib/supabase";
import { cn, formatDate } from "@/lib/utils";

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

interface Ctx {
  paperId: string;
  teamId: string;
  userId: string;
}

export function PaperEngagement(ctx: Ctx) {
  return (
    <div className="mt-5 flex flex-col gap-5 border-t border-border pt-4">
      <Reactions {...ctx} />
      <Comments {...ctx} />
    </div>
  );
}

function Reactions({ paperId, teamId, userId }: Ctx) {
  const qc = useQueryClient();
  const key = ["reactions", paperId, teamId];
  const { data } = useQuery({
    queryKey: key,
    queryFn: async (): Promise<ReactionRow[]> => {
      const { data, error } = await supabase
        .from("reactions")
        .select("emoji, user_id")
        .eq("paper_id", paperId)
        .eq("team_id", teamId);
      if (error) throw error;
      return (data ?? []) as ReactionRow[];
    },
  });
  const rows = data ?? [];

  async function toggle(emoji: string) {
    const mine = rows.some((r) => r.emoji === emoji && r.user_id === userId);
    if (mine) {
      await supabase
        .from("reactions")
        .delete()
        .eq("paper_id", paperId)
        .eq("team_id", teamId)
        .eq("user_id", userId)
        .eq("emoji", emoji);
    } else {
      await supabase
        .from("reactions")
        .insert({ paper_id: paperId, team_id: teamId, user_id: userId, emoji });
    }
    await qc.invalidateQueries({ queryKey: key });
  }

  return (
    <div className="flex flex-wrap gap-2">
      {EMOJIS.map((e) => {
        const count = rows.filter((r) => r.emoji === e).length;
        const mine = rows.some((r) => r.emoji === e && r.user_id === userId);
        return (
          <button
            key={e}
            type="button"
            onClick={() => toggle(e)}
            className={cn(
              "rounded-full border px-2.5 py-1 text-sm transition",
              mine ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:border-accent",
            )}
          >
            {e}
            {count > 0 && <span className="ml-1 font-mono text-xs">{count}</span>}
          </button>
        );
      })}
    </div>
  );
}

function Comments({ paperId, teamId, userId }: Ctx) {
  const qc = useQueryClient();
  const commentsKey = ["comments", paperId, teamId];

  const { data: comments } = useQuery({
    queryKey: commentsKey,
    queryFn: async (): Promise<CommentRow[]> => {
      const { data, error } = await supabase
        .from("comments")
        .select("id, body, created_at, author_id, profiles(display_name)")
        .eq("paper_id", paperId)
        .eq("team_id", teamId)
        .order("created_at");
      if (error) throw error;
      return (data ?? []) as unknown as CommentRow[];
    },
  });

  const { data: members } = useQuery({
    queryKey: ["members", teamId],
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

  const teammates = (members ?? []).filter((m) => m.user_id !== userId);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const { data: inserted, error: insErr } = await supabase
        .from("comments")
        .insert({ paper_id: paperId, team_id: teamId, author_id: userId, body: body.trim() })
        .select("id")
        .single();
      if (insErr) throw insErr;

      if (mentionIds.length > 0) {
        const { error: mErr } = await supabase.from("mentions").insert(
          mentionIds.map((uid) => ({
            paper_id: paperId,
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
        {list.length > 0 ? `${list.length} comment(s)` : "Comments"}
      </div>

      {list.map((c) => (
        <div key={c.id} className="flex gap-2.5">
          <Avatar name={c.profiles?.display_name ?? "?"} size={26} />
          <div className="min-w-0">
            <div className="text-xs">
              <span className="font-semibold text-fg">{c.profiles?.display_name ?? "Someone"}</span>
              <span className="ml-2 font-mono text-muted">{formatDate(c.created_at)}</span>
            </div>
            <div className="mt-0.5 whitespace-pre-wrap text-sm">{c.body}</div>
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
