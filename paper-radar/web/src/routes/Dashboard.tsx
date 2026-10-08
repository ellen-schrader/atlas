import { type CSSProperties, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { ContinueReadingCard, ContinueReadingHeading } from "@/components/home/ContinueReading";
import { LabFeed } from "@/components/home/LabFeed";
import { gridColumns, homeFrame } from "@/components/home/layout";
import { Omnibar } from "@/components/home/Omnibar";
import { RecommendationsRow } from "@/components/home/Recommendations";
import { TagVolume } from "@/components/home/TagVolume";
import { Trending } from "@/components/home/Trending";
import { usePaperModal } from "@/components/PaperModal";
import { useEngagementCounts } from "@/hooks/useEngagementCounts";
import { useNewSinceLastVisit } from "@/hooks/useLastVisit";
import { useProfile } from "@/hooks/useProfile";
import { usePaperSearch } from "@/hooks/usePaperSearch";
import { useReadingList } from "@/hooks/useReadingList";
import { useReadPapers } from "@/hooks/useReadPapers";
import { isWakingRecommendations, useRecommendations } from "@/hooks/useRecommendations";
import { useTagVolume, useTrendingLabs, useTrendingTags } from "@/hooks/useTrends";
import { supabase } from "@/lib/supabase";
import { useAppContext } from "@/routes/Layout";

/** Collapses a query into what a panel shows: skeleton, error line, or data. */
function queryState(q: { isLoading: boolean; isError: boolean }): "loading" | "error" | "ready" {
  return q.isLoading ? "loading" : q.isError ? "error" : "ready";
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

/** Home (docs/dashboard.md). Every block sits on one N-column track set so edges
 *  line up row to row; N comes from the shell's width (components/home/layout). */
export default function Dashboard() {
  const { team, userId, displayName, shellWidth } = useAppContext();
  const { openPaper } = usePaperModal();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const frame = homeFrame(shellWidth);
  const { cols, tier } = frame;
  const mobile = tier === "mobile";
  const wide = cols >= 3;

  const search = usePaperSearch(team.id, "");
  const posts = (search.data?.pages ?? []).flat();
  const { data: counts } = useEngagementCounts(
    team.id,
    posts.map((p) => p.papers.id),
  );
  const { data: toRead } = useReadingList(userId, team.id);
  const { data: readIds } = useReadPapers(userId, team.id);
  // 12, so the widest layouts can fill 4–5 cards and still have a page to scroll to.
  const recs = useRecommendations(team.id, "discover", 12);
  const { data: newCount } = useNewSinceLastVisit(team.id);
  const { data: profile } = useProfile(userId);
  const trendingTags = useTrendingTags(team.id);
  const trendingLabs = useTrendingLabs(team.id);
  const tagRows = trendingTags.data ?? [];
  const volume = useTagVolume(
    team.id,
    tagRows.map((t) => t.tag),
  );
  // Shared between Trending and Tag volume: hovering either highlights both.
  const [hoveredTag, setHoveredTag] = useState<string | null>(null);
  const [touch] = useState(() => window.matchMedia?.("(hover: none)").matches ?? false);

  async function markPaperRead(paperId: string) {
    await supabase
      .from("paper_status")
      .update({ status: "read", updated_at: new Date().toISOString() })
      .eq("user_id", userId)
      .eq("team_id", team.id)
      .eq("paper_id", paperId);
    void qc.invalidateQueries({ queryKey: ["reading-list"] });
    void qc.invalidateQueries({ queryKey: ["read-papers"] });
  }

  const firstName = displayName.split(/[\s@]/)[0];
  const bookmarkedIds = new Set((toRead ?? []).map((r) => r.paper_id));

  // The single next paper to read: the oldest still-unread saved one (the list is
  // newest-first, so that's the tail). useReadingList returns read papers too —
  // saving is independent of progress — so filter them out here.
  const queue = (toRead ?? []).filter((r) => r.status !== "read");
  const nextUp = queue[queue.length - 1];

  const greetingBlock = (
    <div className="min-w-0">
      <h1
        className={
          mobile
            ? "font-serif text-2xl font-semibold leading-tight tracking-tight"
            : "text-display font-serif font-semibold tracking-tight"
        }
      >
        {greeting()}, {firstName}
      </h1>
      <p className="mt-1.5 text-sm text-muted">
        {newCount == null ? (
          <>What’s moving in {team.name}.</>
        ) : newCount === 0 ? (
          <>Nothing new in {team.name} since your last visit.</>
        ) : (
          <>
            <span className="text-fg">
              {newCount} new {newCount === 1 ? "paper" : "papers"}
            </span>{" "}
            in {team.name} since your last visit.
          </>
        )}
      </p>
    </div>
  );
  const omnibar = <Omnibar teamId={team.id} teamName={team.name} mobile={mobile} />;
  const continueHeading = (
    <ContinueReadingHeading
      count={queue.length}
      onOpenList={() => navigate("/reading")}
      className={wide ? "mb-0" : undefined}
    />
  );
  const continueCard = (
    <ContinueReadingCard
      next={nextUp}
      compact={!mobile}
      onOpen={() => nextUp && openPaper(nextUp.paper_id)}
      onMarkRead={() => nextUp && void markPaperRead(nextUp.paper_id)}
    />
  );

  const recommendations = (
    <RecommendationsRow
      recs={{
        results: recs.data?.results ?? [],
        isLoading: recs.isLoading,
        isError: recs.isError,
        waking: isWakingRecommendations(recs),
      }}
      tier={tier}
      perPage={frame.recsPerPage}
      teamId={team.id}
      teamName={team.name}
      // Unknown until the profile loads: say "Tune" rather than flash the nudge.
      hasProfile={profile ? Boolean(profile.profile_md?.trim()) : true}
      userId={userId}
      bookmarkedIds={bookmarkedIds}
      onOpen={openPaper}
      onTune={() => navigate("/settings")}
    />
  );

  const feed = (
    <LabFeed
      posts={posts}
      loading={search.isLoading}
      counts={counts}
      readIds={readIds}
      bookmarkedIds={bookmarkedIds}
      teamId={team.id}
      teamName={team.name}
      joinCode={team.join_code}
      userId={userId}
      mobile={mobile}
      onOpen={openPaper}
      onBrowseAll={() => navigate("/papers")}
    />
  );

  const rail = [
    <Trending
      key="trending"
      tags={tagRows}
      labs={trendingLabs.data ?? []}
      tagsState={queryState(trendingTags)}
      labsState={queryState(trendingLabs)}
      hoveredTag={hoveredTag}
      onHoverTag={setHoveredTag}
      onTag={(tag) => navigate(`/papers?tag=${encodeURIComponent(tag)}`)}
      // No author filter in Papers; its full-text search covers author names
      // (in any position, so this can also find the PI's non-senior papers).
      onLab={(lab) => navigate(`/papers?q=${encodeURIComponent(lab)}`)}
    />,
    <TagVolume
      key="volume"
      className="flex-1"
      tags={tagRows}
      series={volume.data ?? []}
      loading={trendingTags.isLoading || volume.isLoading}
      hoveredTag={hoveredTag}
      onHoverTag={setHoveredTag}
      touch={touch}
    />,
  ];

  const grid: CSSProperties = { gridTemplateColumns: gridColumns(cols), columnGap: 24 };
  const lead: CSSProperties = { gridColumn: `1 / span ${cols - 1}` };

  return (
    <div style={{ padding: frame.padding }}>
      <div
        className="mx-auto flex w-full max-w-[1680px] flex-col"
        style={{ gap: frame.blockGap }}
      >
        {wide ? (
          // Two rows: greeting | "Continue reading" label, then search | card.
          <div className="grid items-end" style={{ ...grid, rowGap: 18 }}>
            <div className="min-w-0" style={{ ...lead, gridRow: 1 }}>
              {greetingBlock}
            </div>
            <div className="min-w-0" style={{ gridColumn: cols, gridRow: 1 }}>
              {continueHeading}
            </div>
            <div className="min-w-0 self-center" style={{ ...lead, gridRow: 2 }}>
              {omnibar}
            </div>
            <div className="min-w-0 self-center" style={{ gridColumn: cols, gridRow: 2 }}>
              {continueCard}
            </div>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-[18px]">
              {greetingBlock}
              {omnibar}
            </div>
            <section className="min-w-0">
              {continueHeading}
              {continueCard}
            </section>
          </>
        )}

        {recommendations}

        {wide ? (
          <div className="grid items-stretch" style={grid}>
            <div className="flex min-w-0 flex-col" style={lead}>
              {feed}
            </div>
            <div className="flex min-w-0 flex-col" style={{ gap: frame.blockGap }}>
              {rail}
            </div>
          </div>
        ) : (
          <>
            {feed}
            {/* Tablet: Trending and Tag volume side by side under the feed. */}
            <div
              className="grid items-stretch"
              style={{
                gridTemplateColumns: tier === "tablet" ? gridColumns(2) : gridColumns(1),
                gap: `${frame.blockGap}px 24px`,
              }}
            >
              {rail}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
