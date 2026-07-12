import { MessageSquare, Smile } from "lucide-react";

import { cn } from "@/lib/utils";

/** Quiet engagement summary for cards and lists — reaction and comment counts
 *  as line-icon + number. Always shows both counts (including 0) so layout stays
 *  put. The full interactive reactions/comments live in `PaperEngagement`. */
export function EngagementSummary({
  reactions,
  comments,
  className,
}: {
  reactions: number;
  comments: number;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-4 text-muted", className)}>
      <span className="text-meta inline-flex items-center gap-1.5 tabular-nums" title="Reactions">
        <Smile size={14} className="text-faint" />
        {reactions}
      </span>
      <span className="text-meta inline-flex items-center gap-1.5 tabular-nums" title="Comments">
        <MessageSquare size={14} className="text-faint" />
        {comments}
      </span>
    </div>
  );
}
