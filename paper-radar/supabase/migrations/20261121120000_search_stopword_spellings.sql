-- Keyword search: a stopword no longer drags in other spellings (#193).
--
-- "Conservation of the tumour microenvironment across organs and species"
-- found nothing, though the paper of that title is in the lab. prefix_tsquery
-- turned "the" into (the:* | theater | theatre | theatergoer | …): "the" is a
-- stopword, so to_tsquery drops it, but the alternatives of the longer words
-- it begins stay — and the query then needs one of them in every paper. Any
-- query with "the", "for" (formalise, …) or another stopword with listed
-- longer words matched only papers about theatres or formalisation.
--
-- A stopword now goes in as before the spelling list (the:*), with no
-- alternatives; to_tsquery drops it as it always has. Every other word is
-- unchanged. Search only: no stored data changes.

create or replace function public.prefix_tsquery(p_q text)
returns tsquery
language sql
stable
set search_path = public
as $$
    select to_tsquery(
        'english',
        (select string_agg(
                    '(' || tok || ':*'
                        || case
                             -- A stopword: to_tsquery drops it, so it must not
                             -- bring alternatives that would outlive it.
                             when to_tsvector('english', tok) = ''::tsvector then ''
                             else coalesce((select string_agg(' | ' || m.alt, '')
                                            from (select alt from public.spelling_matches(tok) limit 20) m), '')
                           end
                        || ')',
                    ' & ')
         from unnest(regexp_split_to_array(lower(coalesce(p_q, '')), '[^a-z0-9]+')) as tok
         where tok <> '')
    );
$$;
