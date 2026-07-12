import { MessageSquare, Smile } from "lucide-react";

import { cn } from "@/lib/utils";

/** Quiet engagement summary for cards and lists — reaction and comment counts
 *  as line-icon + number. Renders nothing when there's no engagement. The full
 *  interactive reactions/comments live in `PaperEngagement`. */
export function EngagementSummary({
  reactions,
  comments,
  className,
}: {
  reactions: number;
  comments: number;
  className?: string;
}) {
  if (!reactions && !comments) return null;
  return (
    <div className={cn("flex items-center gap-4 text-muted", className)}>
      {reactions > 0 && (
        <span className="text-meta inline-flex items-center gap-1.5 tabular-nums">
          <Smile size={14} className="text-faint" />
          {reactions}
        </span>
      )}
      {comments > 0 && (
        <span className="text-meta inline-flex items-center gap-1.5 tabular-nums">
          <MessageSquare size={14} className="text-faint" />
          {comments}
        </span>
      )}
    </div>
  );
}
