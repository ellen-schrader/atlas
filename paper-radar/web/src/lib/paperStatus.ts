/** Reading progress. Independent of `saved` — see 20261006120000.
 *
 *  This module also held `deleteIfDefault`, which dropped a paper_status row
 *  that had fallen back to meaning nothing (not saved, no progress). It existed
 *  because recommend_papers excluded every paper with ANY row, so the row left
 *  behind by un-saving buried the paper in Discover — the opposite of what
 *  un-saving means. 20261007130000 asks the question properly in SQL instead,
 *  so there is nothing to clean up at four call sites any more.
 */
export type Progress = "unread" | "reading" | "read";
