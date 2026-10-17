-- doi_normalised_test.sql — papers.doi and paper_aliases.doi only ever hold
-- norm_doi's form: lowercased, no resolver prefix, no surrounding slashes.

begin;
select plan(9);

select is(public.norm_doi(' https://doi.org/10.1158/2159-8290.CD-25-1745/ '),
    '10.1158/2159-8290.cd-25-1745', 'norm_doi folds case, prefix, slashes and spaces');
select is(public.norm_doi('doi:'), null, 'a DOI that folds to nothing is null');

insert into public.papers (id, doi, url, url_norm) values
    ('e8000000-0000-0000-0000-0000000000c1', '10.1158/2159-8290.cd-25-1745', 'https://x/1', 'doi-n/1');

select throws_ok(
    $$ insert into public.papers (doi, url, url_norm)
       values ('10.1158/2159-8290.CD-25-1745', 'https://x/2', 'doi-n/2') $$,
    '23514', null, 'a mixed-case DOI is refused');
select throws_ok(
    $$ insert into public.papers (doi, url, url_norm)
       values ('https://doi.org/10.1/abc', 'https://x/3', 'doi-n/3') $$,
    '23514', null, 'a DOI with its resolver prefix is refused');
select throws_ok(
    $$ insert into public.papers (doi, url, url_norm) values ('', 'https://x/4', 'doi-n/4') $$,
    '23514', null, 'an empty DOI is refused');
select throws_ok(
    $$ insert into public.papers (doi, url, url_norm)
       values ('10.1158/2159-8290.cd-25-1745', 'https://x/5', 'doi-n/5') $$,
    '23505', null, 'the same DOI twice is refused');
select lives_ok(
    $$ insert into public.papers (doi, url, url_norm) values (null, 'https://x/6', 'doi-n/6') $$,
    'a paper without a DOI is fine');

select throws_ok(
    $$ insert into public.paper_aliases (paper_id, kind, reason, doi)
       values ('e8000000-0000-0000-0000-0000000000c1', 'preprint', 'crossref', '10.1101/ABC') $$,
    '23514', null, 'an alias DOI in another form is refused');
select lives_ok(
    $$ insert into public.paper_aliases (paper_id, kind, reason, doi)
       values ('e8000000-0000-0000-0000-0000000000c1', 'preprint', 'crossref', '10.1101/abc') $$,
    'an alias DOI in norm_doi form is fine');

select * from finish();
rollback;
