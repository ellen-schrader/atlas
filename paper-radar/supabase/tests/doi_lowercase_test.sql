-- doi_lowercase_test.sql — papers.doi only ever holds the folded form.

begin;
select plan(3);

insert into public.papers (id, doi, url, url_norm) values
    ('e8000000-0000-0000-0000-0000000000c1', '10.1158/2159-8290.cd-25-1745', 'https://x/1', 'doi-lc/1');

select throws_ok(
    $$ insert into public.papers (doi, url, url_norm)
       values ('10.1158/2159-8290.CD-25-1745', 'https://x/2', 'doi-lc/2') $$,
    '23514', null, 'a mixed-case DOI is refused');

select throws_ok(
    $$ insert into public.papers (doi, url, url_norm)
       values ('10.1158/2159-8290.cd-25-1745', 'https://x/3', 'doi-lc/3') $$,
    '23505', null, 'the same DOI twice is refused');

select lives_ok(
    $$ insert into public.papers (doi, url, url_norm) values (null, 'https://x/4', 'doi-lc/4') $$,
    'a paper without a DOI is fine');

select * from finish();
rollback;
