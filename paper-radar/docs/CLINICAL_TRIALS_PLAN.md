# Clinical trials: plan

Status: proposal, 18 Oct 2026. Branch `clinical-trials`.
Scope for the MVP (decided 18 Oct): **breast cancer only, and only the Ali Lab can see it.** Broadening to other cancers and other labs comes later.

Source: the three mock-ups in `clinical-trials-brief/` (gitignored): `Questions2` (Collections home), `Trials2` (All trials), `MVP2` (one collection: overview, single trial, compare). All values in them are illustrative.

## 1. What the mock-ups ask for

A new **Clinical trials** section in the sidebar (badge "New") with two entries: **Collections** and **All trials**.

**A trial** is a registered study (NCT ID) that the lab has added. It carries:
- registry facts: name/acronym, NCT, phase, design (randomisation ratio, blinding), arms;
- classification used for filtering and colour: *setting* (neoadjuvant / adjuvant / metastatic), *patient group* (TNBC, HR+/HER2−, HER2-low, HER2+, gBRCA), *therapy class* (immunotherapy, ADC, CDK4/6, PARP, endocrine, chemo);
- a **treatment schema**: phases on a week axis (chemo blocks, surgery, adjuvant), with the experimental drug or placebo as a band above them, for each arm;
- **results**: primary/secondary endpoints, either a rate (pCR, control vs experimental, Δ with CI and its definition) or a hazard ratio (HR, CI, events, median follow-up), plus adverse events (grade ≥3, immune-related, stopped for AEs), data cut-off and analysis population;
- **who was enrolled**: N randomised of N screened, then for each baseline dimension (T stage, nodes, stage, ECOG, TILs, age, PD-L1, menopausal) which categories the protocol *allowed / allowed with conditions / excluded*, and the % enrolled in each, overall or by arm, with its source (Table 1, Table S2) and whether a lab member has verified it;
- **linked papers** with a role (primary · pCR, survival, translational) and how they were linked (NCT ID in abstract, trial name in title, suggested needs review, confirmed by a lab member), plus "N more papers on PubMed cite this trial".

**A collection** is a clinical question owned by the lab ("Does adding checkpoint inhibition to neoadjuvant chemo improve outcomes in early TNBC?"), tagged with setting · group · comparison. It has trials, editors and followers, lab notes, and papers "about the question" (meta-analyses, reviews citing several of its trials).

**Pages**
1. **Collections home** (`Questions2`): search box and quick chips; one tile per collection showing a small comparison plot of the shared endpoint (pCR dumbbells or HR with CI, coloured by therapy class); a *suggested collection* (trials that share setting, group and therapy class but aren't grouped yet, e.g. monarchE + NATALEE); a *recent updates* feed (new paper linked, registry updated, values verified, comments).
2. **All trials** (`Trials2`): multi-select filters (therapy, group, setting, phase) with live counts and removable chips; list view (trial, setting, therapy swatches, group, headline result, collections, papers) and grid view (cards with a mini treatment schema); a compare tray (2+ trials) that can be saved as a collection, with a warning when the trials don't share setting and group; *Add trial*.
3. **Collection page** (`MVP2`):
   - *Overview*: trial rows (mini schema, headline result, verification status, papers), "Add trial" (same question first, then other trials in Atlas), a placeholder trial with "Data not extracted yet · Start extraction", lab notes, and papers grouped as *about the question* vs *reporting a trial*.
   - *Single trial*: PICO, schema, outcome panels, enrolled grid, papers, and **Edit** ("Edited by you · change logged" vs "From ClinicalTrials.gov · checked against protocol").
   - *Compare* (2–4 trials, with the disclaimer "Descriptive comparison across trials, not randomised"): aligned treatment schedules; results as pCR dumbbells and an HR forest (log axis, dashed when not directly comparable, e.g. a stricter pCR definition); a "differs" list (pCR definition, pathology review, EFS event definition, follow-up, post-surgery therapy, enrolment years, region) with "N items not yet extracted"; an enrolment table flagging cells that differ by ≥15 pp from the other trials.
   - Every page has the footer: *For research and evidence review. Registry data can lag protocols. Not a recommendation for individual patients.*

## 1a. Access: Ali Lab only

Atlas has no feature flags today; "Beta" is only a label in `nav.ts`. So this adds a small per-lab switch:

- Migration: `team_features` (whole lab) and `user_features` (one person) tables, written only by the service role, plus `public.has_feature(team_id, feature)`. The flag name is `clinical_trials`.
- **Shipped dark.** PRs merge to `main` with the flag off for every lab, including the Ali Lab, so no user sees anything. Locally the seed turns it on for the seeded lab. When you're happy, one small data migration (`insert into public.team_features (team_id, feature) select id, 'clinical_trials' from public.teams where slug = '<ali-lab slug>'`) turns it on for the Ali Lab through the normal merge-to-main deploy. Nothing gets run against prod by hand.
- **Database:** every RLS policy on the new trial tables requires both `is_team_member(team_id)` and `team_has_feature(team_id, 'clinical_trials')`. So another lab gets nothing even by calling Supabase directly.
- **API:** the `api/trials.py` router checks the flag for the active lab and returns 404, not 403, so it doesn't advertise the feature.
- **Frontend:** the lab's `features` come back with the team, the Clinical trials nav group only renders when the flag is set, and the `/trials/*` routes redirect home otherwise.
- **Jobs:** paper↔trial link detection, the daily refresh and extraction only run for flagged labs, so other labs' papers aren't scanned and cost nothing.
- **MCP:** trial tools (PR 7) are only listed for flagged labs.
- pgTAP tests cover a member of a non-flagged lab seeing zero rows, and the Ali Lab seeing its own.

Widening it later means adding the flag to more labs; removing the gate entirely means dropping the checks.

## 2. Where the data comes from

| Data | Source | How |
|---|---|---|
| Trial identity, phase, arms, interventions, eligibility text, enrolment, status, posted results | ClinicalTrials.gov API v2 (free, no key) | fetched when a trial is added, refreshed daily |
| Paper ↔ trial links | `NCT\d{8}` in a paper's abstract; PubMed's secondary-ID (databank) field; trial acronym in the title | at paper ingest, plus a one-off backfill |
| Setting / group / therapy class | Claude, from the registry record | at add time, editable |
| Treatment schema | Claude, from the registry arms plus the primary paper's methods | at extraction, editable |
| Results, baseline table, eligibility categories, "differs" items | Claude, from the linked papers' full text and supplements | **Start extraction**, then a lab member verifies |
| PubMed papers not yet in Atlas | PubMed search on the NCT ID | the "N more papers cite this trial" hint |

The hard part is the last group. Atlas doesn't store full text today, so extraction needs one of:
(a) Europe PMC / PMC open-access full text, fetched by DOI (free, but often doesn't cover the big trials' supplements), or
(b) a lab member uploads the PDF and the supplement for that trial (always works).
I recommend doing (a) when it's available and falling back to (b). Each extracted number keeps its source (paper, table or figure, page), so the "Table 1 · not yet verified · suggest a correction" pattern in the mock-up works for real.

**Decided 18 Oct:** extraction uses **Claude Opus 5.5**; uploaded and fetched PDFs are **kept**, private to the lab, so every value's source can be opened; open-access full text is **fetched automatically** from Europe PMC (fixed hosts only, size-capped, checked to be a PDF, never executed, and treated as untrusted data by Claude, which has no tools), with upload as the fallback.

## 3. Data model (new migrations)

Trials are global, like `papers`, and visibility goes through a per-lab posts table, like `paper_posts`. Anything a lab adds or edits stays lab-scoped, following the cross-lab-leaks work (#133).

- `trials`: `nct_id` (unique), `acronym`, `title`, `phase`, `status`, `sponsor`, `start_date`, `completion_date`, `enrollment`, `registry` (jsonb: the raw CT.gov record), `registry_updated_at` (CT.gov's last-update date), `fetched_at`.
- `trial_posts (trial_id, team_id, added_by, created_at)`: a lab's "All trials". This is the RLS boundary.
- `trial_facts (trial_id, team_id, setting[], patient_groups[], therapy_classes[], schema jsonb, results jsonb, enrolment jsonb, eligibility jsonb, differs jsonb, extracted_at, model)`: one row per lab and trial.
- `trial_fact_sources (fact_id, path, paper_id, locator, verified_by, verified_at)`: provenance and verification per value, keyed by a JSON path such as `enrolment.t.T2`.
- `trial_fact_edits`: the change log behind "Edit".
- `paper_trials (paper_id, trial_id, team_id, role, link_source, status suggested|confirmed|rejected, confirmed_by)`.
- `trial_collections (id, team_id, title, question, setting, patient_group, comparison, created_by, …)`, `collection_trials`, `collection_papers` (the "about the question" papers), `collection_followers` (any lab member can edit).
- Lab notes: reuse the existing `comments` table with a new target type if it fits; if not, add `collection_notes`.
- `trial_events (team_id, trial_id, kind, payload, created_at)` feeds "Recent updates".

The JSON shapes for `schema`, `results` and `enrolment` follow the mock-up's data structures (phases with weeks and type, drug bands per arm, endpoints of kind rate or HR, dimension → categories → allowed/conditional + share per arm), defined once as pydantic models in `paper_radar/models.py`. That way Claude's structured output, the API and the frontend types all share one definition.

Migration timestamps: the latest on `main` is `20261019130000`, already dated tomorrow, and `account-deletion` holds `20261019140000`. New migrations have to sort after both, so I'd start at `20261019150000`. That breaks the "not ahead of today" rule, but it's the only way they'll apply in order (see Open questions).

## 4. Backend

- `paper_radar/trials/ctgov.py`: CT.gov v2 client (fetch by NCT, map to `trials`), with tests against recorded fixtures.
- `paper_radar/trials/link.py`: NCT and acronym detection, called from `_enrich_and_store` in `api/app.py` and from `api/backfill_trial_links.py`.
- `api/trial_classify.py`: Claude classifies setting, group and therapy class from the registry record (the same `messages.parse` + pydantic pattern as `enrichment.py`).
- `api/trial_extract.py`: Claude extraction from full text into `trial_facts` plus sources. It runs as a background task started by "Start extraction". One trial at a time, with progress and failure stored so the UI can show it.
- `api/trials.py` router: list/filter (with facet counts), add by NCT or search, detail, edit, link/unlink/confirm paper, collections CRUD, follow, compare (2–4 trial IDs → aligned data plus computed "differs" and ≥15 pp flags), events feed, suggested collections (trials sharing setting + group + therapy class that aren't already in one collection together).
- Daily job: add `python -m api.trials_refresh` to `.github/workflows/preprint-watch.yml`. It re-fetches lab trials whose CT.gov last-update date has moved, writes `trial_events` and checks for newly linked papers.
- MCP (later): `search_trials`, `get_trial`, `compare_trials` on the hosted connector, returning Atlas links like the paper tools do.

## 5. Frontend

- `nav.ts`: a "Clinical trials" group with Collections and All trials and a `new` badge (the Sidebar has `beta` today, so this adds a variant). Routes: `/trials`, `/trials/collections`, `/trials/collections/:id` (with `?view=overview|<trial>|compare`).
- Shared components: `TreatmentSchema` (full, mini and card sizes), `EnrolmentGrid`, `OutcomePanel`, `PcrDumbbell`, `HrForest`, `TrialFilters`, `CompareTray`, `LinkProvenance`, `VerifyBadge`, `TrialsDisclaimer`.
- Styling: use the Atlas tokens in `web/src/index.css` and map the mock-up's hex values onto them. The therapy-class and per-trial colours are new categorical palettes. I'll run them through the dataviz skill's validator and keep the shape markers (circle, square, diamond, triangle) the mock-up already uses for the four compare trials, so it still works for colour-blind readers.
- Charts are plain SVG/CSS, as in the mock-up. No chart library needed.

## 6. Delivery in PRs

Each PR gets `/code-review high` before it's called ready.

1. **Trials foundation**: the per-lab feature flag and the Ali Lab switch (section 1a), migrations (`trials`, `trial_posts`, `paper_trials`, RLS and pgTAP tests), the CT.gov client, add-by-NCT, NCT detection at ingest plus backfill, and the API. No UI beyond what's needed to test it.
2. **All trials page**: nav, list and grid, filters with counts, classification, registry-derived PICO, linked papers with provenance and a confirm/reject review, Add trial. The mini schema shows registry arms only until extraction exists.
3. **Collections**: CRUD, collections home (tiles without plots yet), collection overview (trials, papers grouped, notes, follow/edit), Add trial, compare tray → Save as collection.
4. **Extraction and the single-trial view**: full-text fetch/upload, Claude extraction into `trial_facts` with sources, verification and edit with change log, treatment schema, outcome panels, enrolled grid. This is the MVP2 page working end to end.
5. **Compare**: schedules, pCR dumbbells, HR forest, the "differs" list, enrolment diff flags, plus the plots on the collection tiles.
6. **Updates and suggestions**: daily CT.gov refresh, events feed, suggested collections, the "N more papers on PubMed" hint.
7. **MCP tools** for trials.

PRs 1–4 deliver the core of the mock-ups. I'd seed the local stack with the four neoadjuvant TNBC trials (KEYNOTE-522, NeoTRIP, IMpassion031, GeparNuevo) and check every step against the MVP2 page.

## 7. Cost

- ClinicalTrials.gov, PubMed and Europe PMC are free.
- Classification is one small Claude call per trial added, a fraction of a cent each.
- Extraction is the main cost: roughly 50–150k input tokens per trial (two or three papers plus supplements), so a few tens of pence per trial at Sonnet prices. It only runs when someone presses Start extraction, never automatically. At ~10 trials a month that's around £1–3/month.
- The daily refresh is one more step in the existing GitHub Action, with no new Fly machine.

## 8. Open questions for you

1. ~~Scope of the taxonomy~~ Decided: breast cancer only for the MVP. The setting, patient-group and therapy lists are fixed in code (one `breast_cancer` taxonomy module), so a second taxonomy can be added later without a schema change.
2. ~~Shared or per-lab extraction~~ Decided: keep it per lab. Extracted facts, verification and edits all live in lab-scoped rows (`trial_facts` by `team_id`); only the raw registry record in `trials` is shared.
3. ~~Full text~~ Decided: open access first, otherwise a lab member uploads the PDF and supplement.
4. ~~Who can edit a collection~~ Decided: every lab member. No `collection_editors` table; "editors" in the header is derived from who has edited.
5. ~~Migration date~~ Decided: everything on `main` is applied, so new migrations just sort after the latest one.
6. ~~First milestone~~ Decided: PRs 1–4 first, then compare. All merged dark (see 1a).
7. **Ali Lab slug.** Only needed for the final switch-on migration, once you're happy with the feature.
