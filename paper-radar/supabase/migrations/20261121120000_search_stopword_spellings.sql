-- Keyword search: a stopword no longer drags in other spellings (#193).
--
-- "Conservation of the tumour microenvironment across organs and species"
-- found nothing, though the paper of that title is in the lab. prefix_tsquery
-- turned "the" into (the:* | theater | theatre | theatergoer | …): "the" is a
-- stopword, so to_tsquery drops it, but the alternatives of the longer words
-- it begins stay, and the query then needs one of them in every paper. Any
-- query with "the", "for" (formalise, …) or another stopword with listed
-- longer words matched only papers about theatres or formalisation.
--
--   1. A word that to_tsquery would drop goes in on its own (the:*), with no
--      alternatives, as it did before spelling variants. The test is
--      to_tsquery's own: does tok:* leave anything? So the alternatives can
--      never outlive the word they came from.
--   2. A query of nothing but stopwords ("the", "for", "of the") gives NULL,
--      not an empty tsquery. search_papers reads NULL as "no text filter", so
--      typing "for" on the way to "formalin" shows the lab's papers rather
--      than flashing "No papers". An empty tsquery matched nothing.
--
-- Every other word is unchanged. Search only: no stored data changes.

create or replace function public.prefix_tsquery(p_q text)
returns tsquery
language sql
stable
set search_path = public
as $$
    select case when numnode(t.q) = 0 then null else t.q end
    from (
        select to_tsquery(
            'english',
            (select string_agg(
                        '(' || tok || ':*'
                            || case
                                 when numnode(to_tsquery('english', tok || ':*')) = 0 then ''
                                 else coalesce((select string_agg(' | ' || m.alt, '')
                                                from (select alt from public.spelling_matches(tok) limit 20) m), '')
                               end
                            || ')',
                        ' & ')
             from unnest(regexp_split_to_array(lower(coalesce(p_q, '')), '[^a-z0-9]+')) as tok
             where tok <> '')
        ) as q
    ) t;
$$;
