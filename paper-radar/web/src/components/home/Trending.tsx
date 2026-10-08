import { useState } from "react";
import { Check, Plus } from "lucide-react";

import { Avatar } from "@/components/Avatar";
import { SectionHeading, Segmented } from "@/components/home/HomeSection";
import type { TrendingLab, TrendingTag } from "@/hooks/useTrends";
import { cn } from "@/lib/utils";

type Tab = "tags" | "labs";
type PanelState = "loading" | "error" | "ready";

/** A change of at least this many papers counts as a big rise (accent). */
const BIG_RISE = 4;

export function formatChange(n: number, prev: number): string {
  const d = n - prev;
  return d > 0 ? `+${d}` : d < 0 ? `−${-d}` : "0";
}

/** "Trending · 30 days": top tags (with the previous 30 days as a track behind
 *  each bar) or the labs (last authors) whose papers were shared most. Hovering a tag row highlights the same band in Tag
 *  volume via `hoveredTag`; this list is also the chart's accessible equivalent. */
export function Trending({
  tags,
  labs,
  tagsState,
  labsState,
  hoveredTag,
  onHoverTag,
  onTag,
  onLab,
  followed,
  followReady,
  onToggleFollow,
  className,
}: {
  tags: TrendingTag[];
  labs: TrendingLab[];
  tagsState: PanelState;
  labsState: PanelState;
  hoveredTag: string | null;
  onHoverTag: (tag: string | null) => void;
  onTag: (tag: string) => void;
  onLab: (lab: string) => void;
  /** Tags the user follows, and how to follow / unfollow one. */
  followed: Set<string>;
  /** False until the profile has loaded: following before then would overwrite it. */
  followReady: boolean;
  onToggleFollow: (tag: string) => void;
  className?: string;
}) {
  const [tab, setTab] = useState<Tab>("tags");
  const state = tab === "tags" ? tagsState : labsState;
  const max = Math.max(1, ...tags.flatMap((t) => [t.n, t.prev]));

  return (
    <section className={cn("flex min-w-0 flex-col", className)}>
      <SectionHeading
        title="Trending · 30 days"
        right={
          <Segmented
            value={tab}
            onChange={setTab}
            label="Trending by"
            options={[
              { value: "tags", label: "Tags" },
              { value: "labs", label: "Labs" },
            ]}
          />
        }
      />
      <div className="rounded-card border border-border bg-surface p-2">
        {state === "loading" ? (
          <div className="flex flex-col gap-3 p-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-7 animate-pulse rounded bg-surface-2" />
            ))}
          </div>
        ) : state === "error" ? (
          <Empty>Trends are unavailable right now.</Empty>
        ) : tab === "tags" ? (
          tags.length === 0 ? (
            <Empty>No tagged papers in the last 30 days.</Empty>
          ) : (
            <>
              <ul onMouseLeave={() => onHoverTag(null)}>
                {tags.map((t) => {
                  const rising = t.n > t.prev;
                  return (
                    <li
                      key={t.tag}
                      onMouseEnter={() => onHoverTag(t.tag)}
                      className={cn(
                        "flex items-start rounded-control transition",
                        hoveredTag === t.tag && "bg-surface-2",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => onTag(t.tag)}
                        onFocus={() => onHoverTag(t.tag)}
                        onBlur={() => onHoverTag(null)}
                        aria-label={`${t.tag}: ${t.n} papers in 30 days, ${formatChange(t.n, t.prev)} on the previous 30`}
                        className="block min-h-11 min-w-0 flex-1 rounded-control py-2 pl-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      >
                        <span className="flex items-baseline gap-2">
                          <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-fg">
                            {t.tag}
                          </span>
                          <span className="font-mono text-[13px] tabular-nums text-fg">{t.n}</span>
                          <span
                            className={cn(
                              "w-7 text-right font-mono text-[12px] tabular-nums",
                              t.n - t.prev >= BIG_RISE ? "text-accent" : "text-muted",
                            )}
                          >
                            {formatChange(t.n, t.prev)}
                          </span>
                        </span>
                        {/* previous 30 days = the 6px track; current = the 3px bar on it */}
                        <span className="relative mt-1.5 block h-1.5" aria-hidden>
                          <span
                            className="absolute inset-y-0 left-0 rounded-full bg-border-strong"
                            style={{ width: `${(t.prev / max) * 100}%` }}
                          />
                          <span
                            className={cn(
                              "absolute left-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full",
                              rising ? "bg-accent/80" : "bg-faint",
                            )}
                            style={{ width: `${(t.n / max) * 100}%` }}
                          />
                        </span>
                      </button>
                      <FollowToggle
                        tag={t.tag}
                        following={followed.has(t.tag)}
                        disabled={!followReady}
                        onToggle={() => onToggleFollow(t.tag)}
                      />
                    </li>
                  );
                })}
              </ul>
              <div className="flex items-center gap-4 px-2.5 pb-1 pt-2 text-[11px] text-muted">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-[3px] w-3 rounded-full bg-accent/80" aria-hidden /> last 30 days
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-1.5 w-3 rounded-full bg-border-strong" aria-hidden /> previous 30 days
                </span>
              </div>
            </>
          )
        ) : labs.length === 0 ? (
          <Empty>No papers in the last 30 days.</Empty>
        ) : (
          <ul>
            {labs.map((a) => (
              <li key={a.lab}>
                <button
                  type="button"
                  onClick={() => onLab(a.lab)}
                  title={`${a.lab} is the last author on these papers`}
                  className="flex min-h-11 w-full items-center gap-3 rounded-control px-2.5 py-2 text-left transition hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  <Avatar name={a.lab} size={26} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{a.lab} lab</span>
                    <span className="block truncate text-meta text-muted">
                      shared by {a.sharers} {a.sharers === 1 ? "person" : "people"}
                    </span>
                  </span>
                  <span className="font-mono text-[13px] tabular-nums text-fg">{a.n}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

/** Follow / unfollow a tag in place. Quiet until hovered unless already
 *  followed, so the list still reads as data first. */
function FollowToggle({
  tag,
  following,
  disabled,
  onToggle,
}: {
  tag: string;
  following: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      aria-pressed={following}
      aria-label={following ? `Unfollow ${tag}` : `Follow ${tag}`}
      title={following ? "Following — papers with this tag rank higher for you" : "Follow this tag"}
      className={cn(
        "tap-target mt-1.5 grid h-7 w-7 shrink-0 place-items-center rounded-control transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        following ? "text-fg" : "text-faint hover:text-fg",
        "disabled:opacity-40",
      )}
    >
      {following ? <Check size={14} /> : <Plus size={14} />}
    </button>
  );
}

function Empty({ children }: { children: string }) {
  return <p className="px-2.5 py-6 text-center text-sm text-muted">{children}</p>;
}
