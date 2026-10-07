import type { CSSProperties, ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { ContinueReadingCard, ContinueReadingHeading } from "@/components/home/ContinueReading";
import { LabFeed } from "@/components/home/LabFeed";
import { gridColumns, homeFrame } from "@/components/home/layout";
import { Omnibar } from "@/components/home/Omnibar";
import { RecommendationsRow } from "@/components/home/Recommendations";
import { usePaperModal } from "@/components/PaperModal";
import { useEngagementCounts } from "@/hooks/useEngagementCounts";
import { usePaperSearch } from "@/hooks/usePaperSearch";
import { useReadingList } from "@/hooks/useReadingList";
import { useReadPapers } from "@/hooks/useReadPapers";
import { isWakingRecommendations, useRecommendations } from "@/hooks/useRecommendations";
import { supabase } from "@/lib/supabase";
import { useAppContext } from "@/routes/Layout";

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
      <p className="mt-1.5 text-sm text-muted">What’s moving in {team.name}.</p>
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
        coldStart: Boolean(recs.data?.cold_start),
      }}
      tier={tier}
      perPage={frame.recsPerPage}
      teamId={team.id}
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
      userId={userId}
      mobile={mobile}
      onOpen={openPaper}
      onBrowseAll={() => navigate("/papers")}
    />
  );

  const rail: ReactNode[] = [];

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
            {rail.length > 0 && (
              <div
                className="grid items-stretch"
                style={{
                  gridTemplateColumns: tier === "tablet" ? gridColumns(2) : gridColumns(1),
                  gap: `${frame.blockGap}px 24px`,
                }}
              >
                {rail}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
