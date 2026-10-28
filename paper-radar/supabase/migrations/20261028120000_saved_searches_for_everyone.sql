-- 20261028120000_saved_searches_for_everyone.sql — saved searches (#164) are on
-- for every lab, so the 'saved_searches' switch no longer gates anything. Drop
-- its rows, so my_features and `python -m api.features list` don't show it.

delete from public.team_features where feature = 'saved_searches';
delete from public.user_features where feature = 'saved_searches';
