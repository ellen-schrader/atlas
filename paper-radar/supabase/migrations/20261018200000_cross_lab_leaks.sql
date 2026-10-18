-- 20261018200000_cross_lab_leaks.sql — what a lab can read about another lab's
-- activity on a paper they both hold (issue #133).
--
-- Papers are global, so paper_edits and paper_aliases are readable by every lab
-- holding the paper (their policies copy papers_select). That is right for what
-- they say about the *paper* — what the title used to be, where the preprint is —
-- but some columns say who in another lab acted on it:
--
--   paper_edits.edited_by       the editor's user id. profiles RLS hides the name
--                               across labs, but the id is still a stable handle:
--                               "the same person corrected these five papers".
--   paper_aliases.snapshot      the merged-away row, including its edited_by,
--                               edited_at and edited_fields, and the created_at of
--                               a row perhaps only another lab held.
--   paper_aliases.merged_by     who confirmed a merge, which any member of any
--                               lab holding either paper may do.
--   paper_aliases.reason        'manual' says a person did it.
--
-- So members get SELECT on the other columns only. The rows stay as visible as
-- before: an edit's before/after is the point of the history (the person who
-- notices a bad correction is often in another lab), and a preprint link is
-- public bibliographic information. Everything that needs the hidden columns —
-- repairing a merge by hand, the merge and promote functions — runs as the
-- service role or as a definer function, and is untouched.
--
-- Column grants make `select *` (or `paper_aliases(*)` in an embed) fail with
-- "permission denied" for members rather than quietly returning less; name the
-- columns. A history UI that wants "edited by Ada" for an editor in the
-- viewer's own lab should get it from a definer function that returns
-- edited_by only when the two share a lab, not by granting the column back.
--
-- papers.edited_by is left as it is: the card's "Edited … outside your lab"
-- line reads it, and narrowing it needs a column list on every papers read.

revoke select on public.paper_edits from authenticated;
grant select (id, paper_id, kind, edited_at, before, after)
    on public.paper_edits to authenticated;

revoke select on public.paper_aliases from authenticated;
grant select (id, paper_id, kind, doi, url, url_norm, venue, old_paper_id, created_at)
    on public.paper_aliases to authenticated;
