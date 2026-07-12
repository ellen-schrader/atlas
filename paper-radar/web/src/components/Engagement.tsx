import { type FormEvent, type KeyboardEvent, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Avatar } from "@/components/Avatar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { type Member, useMembers } from "@/hooks/useMembers";
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

/** The `@…` token being typed immediately before the caret, if any. Requires the
 *  `@` to start a word, and no whitespace between it and the caret — so a name
 *  that's already been completed ("@Maya Chen ") stops matching. */
function activeMention(text: string, caret: number): { query: string; start: number } | null {
  const m = /(?:^|\s)@([^\s@]*)$/.exec(text.slice(0, caret));
  if (!m) return null;
  const query = m[1];
  return { query, start: caret - query.length - 1 };
}

/** Split a posted comment into plain runs and `@Name` runs that resolve to a
 *  teammate. Longest names first so "@Ada Lovelace" wins over "@Ada". */
function splitMentions(text: string, members: Member[]): { text: string; member?: Member }[] {
  const named = members.filter((m) => m.profiles?.display_name);
  if (named.length === 0) return [{ text }];

  const byName = new Map(named.map((m) => [m.profiles!.display_name.toLowerCase(), m]));
  const pattern = named
    .map((m) => m.profiles!.display_name)
    .sort((a, b) => b.length - a.length)
    .map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");
  const re = new RegExp(`@(${pattern})`, "gi");

  const out: { text: string; member?: Member }[] = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ text: text.slice(last, at) });
    out.push({ text: m[0], member: byName.get(m[1].toLowerCase()) });
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}

/** A posted comment, with @mentions highlighted and hoverable. */
function CommentBody({ text, members }: { text: string; members: Member[] }) {
  return (
    <div className="mt-0.5 whitespace-pre-wrap text-sm">
      {splitMentions(text, members).map((part, i) =>
        part.member ? (
          <MentionTag key={i} member={part.member} label={part.text} />
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </div>
  );
}

/** A highlighted @mention that reveals a quick profile summary on hover. */
function MentionTag({ member, label }: { member: Member; label: string }) {
  const name = member.profiles?.display_name ?? "member";
  const bio = member.profiles?.profile_md?.trim();
  return (
    <span className="group/mention relative inline-block">
      <span className="cursor-default rounded-chip bg-accent-weak px-1 font-medium text-accent">
        {label}
      </span>
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute bottom-full left-0 z-30 mb-1.5 hidden w-64",
          "rounded-card border border-border bg-surface p-3 text-left shadow-lg",
          "group-hover/mention:block",
        )}
      >
        <span className="flex items-center gap-2">
          <Avatar name={name} size={28} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold text-fg">{name}</span>
            <span className="block text-xs capitalize text-muted">{member.role}</span>
          </span>
        </span>
        <span className="mt-2 block whitespace-normal text-xs leading-relaxed text-muted">
          {bio ? (bio.length > 160 ? `${bio.slice(0, 160)}…` : bio) : "No research profile yet."}
        </span>
      </span>
    </span>
  );
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

  // Shared with Reactions (same ["members", teamId] cache key) — one source of
  // truth for names, roles, and the profile shown on an @mention hover.
  const { data: members } = useMembers(teamId);

  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");

  // @-mention autocomplete
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [mention, setMention] = useState<{ query: string; start: number } | null>(null);
  const [activeIdx, setActiveIdx] = useState(0);

  const teammates = cfg.supportsMentions ? (members ?? []).filter((m) => m.user_id !== userId) : [];

  const matches = mention
    ? teammates
        .filter((m) =>
          (m.profiles?.display_name ?? "").toLowerCase().includes(mention.query.toLowerCase()),
        )
        .slice(0, 5)
    : [];
  const showMenu = matches.length > 0;

  /** Recompute the active @-token from the textarea's live value + caret. */
  function syncMention() {
    const el = inputRef.current;
    if (!el || !cfg.supportsMentions) return;
    setMention(activeMention(el.value, el.selectionStart ?? 0));
    setActiveIdx(0);
  }

  /** Replace the typed `@query` with the picked teammate's full name. */
  function pickMention(m: Member) {
    const el = inputRef.current;
    if (!el || !mention) return;
    const name = m.profiles?.display_name ?? "member";
    const caret = el.selectionStart ?? body.length;
    const next = `${body.slice(0, mention.start)}@${name} ${body.slice(caret)}`;
    const pos = mention.start + name.length + 2; // past "@name "
    setBody(next);
    setMention(null);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(pos, pos);
    });
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (!showMenu) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => (i + 1) % matches.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => (i - 1 + matches.length) % matches.length);
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault(); // pick instead of newline
      pickMention(matches[activeIdx]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setMention(null);
    }
  }

  /** Who the comment tags: any teammate whose name appears as "@Name" in the body.
   *  Derived from the text (not click state), so hand-typed mentions notify too. */
  function mentionedIds(text: string): string[] {
    const lower = text.toLowerCase();
    return teammates
      .filter((m) => {
        const name = m.profiles?.display_name;
        return name && lower.includes(`@${name.toLowerCase()}`);
      })
      .map((m) => m.user_id);
  }

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

      const tagged = cfg.supportsMentions ? mentionedIds(body) : [];
      if (tagged.length > 0) {
        // Each row notifies that user (bell) and adds the paper to their to-read
        // list via the on_mention_created trigger.
        const { error: mErr } = await supabase.from("mentions").insert(
          tagged.map((uid) => ({
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
      setMention(null);
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
                <CommentBody text={c.body} members={members ?? []} />
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
        <div className="relative">
          <Textarea
            ref={inputRef}
            rows={2}
            value={body}
            onChange={(e) => {
              setBody(e.target.value);
              syncMention();
            }}
            onKeyDown={onKeyDown}
            onKeyUp={syncMention}
            onClick={syncMention}
            onBlur={() => setTimeout(() => setMention(null), 120)} // let a click land first
            placeholder={
              cfg.supportsMentions
                ? "Add a comment… type @ to tag a teammate"
                : "Add a comment for your team…"
            }
          />

          {showMenu && (
            <ul
              role="listbox"
              className="absolute z-20 mt-1 w-64 overflow-hidden rounded-control border border-border bg-surface shadow-lg"
            >
              {matches.map((m, i) => (
                <li key={m.user_id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={i === activeIdx}
                    onMouseDown={(e) => e.preventDefault()} // keep focus in the textarea
                    onMouseEnter={() => setActiveIdx(i)}
                    onClick={() => pickMention(m)}
                    className={cn(
                      "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm transition",
                      i === activeIdx ? "bg-accent-weak text-accent" : "hover:bg-surface-2",
                    )}
                  >
                    <Avatar name={m.profiles?.display_name ?? "?"} size={20} />
                    <span className="truncate">{m.profiles?.display_name ?? "member"}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

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
