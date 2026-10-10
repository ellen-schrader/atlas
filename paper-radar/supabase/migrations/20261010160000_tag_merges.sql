-- First reviewed batch of tag merges (80 groups, 102 tags), proposed by
-- api/propose_tag_merges.py against the live library (1,471 distinct tags)
-- and approved by Ellen on 2026-10-10. Mostly plurals, hyphenation variants
-- and abbreviations (scrna-seq, nsclc, cytof, llm); a few synonyms. After
-- review: broad-into-narrow merges were left out (ffpe, tgf-beta, brca1-brca2,
-- cgas-sting-pathway, target-discovery) because an alias blocks the broad tag
-- for good, and the immune-checkpoint variants share one kept tag.
--
-- 1. Insert the aliases: every future write uses the kept tag (the clean_tags
--    trigger, 20261010140000_tag_hygiene.sql). tag_aliases' flat-table trigger
--    rejects any chain, so a bad row fails the whole migration.
-- 2. Copy the current tags of every row the merges will change into
--    tag_merge_backup, so any merge can be reversed later row by row.
-- 3. apply_tag_cleanup() rewrites the stored tags on papers, lab posts,
--    follows and the undo archive.

create table if not exists public.tag_merge_backup (
    batch      text        not null,
    tbl        text        not null,
    row_id     uuid        not null,
    old_tags   jsonb       not null,
    created_at timestamptz not null default now(),
    primary key (batch, tbl, row_id)
);

comment on table public.tag_merge_backup is
    'Tags as they were before a tag_aliases batch rewrote them, for reversing a merge.';

-- Service role only, like tag_aliases.
alter table public.tag_merge_backup enable row level security;
grant select, insert, delete on public.tag_merge_backup to service_role;

insert into public.tag_aliases (alias, canonical) values
    ('scrna-seq', 'single-cell-rna-seq'),
    ('single-cell-rna-sequencing', 'single-cell-rna-seq'),
    ('tertiary-lymphoid-organs', 'tertiary-lymphoid-structures'),
    ('foundation-models', 'foundation-model'),
    ('computational-methods', 'computational-method'),
    ('spatial-multiomics', 'spatial-multi-omics'),
    ('immune-checkpoint-blockade', 'immune-checkpoint-inhibitors'),
    ('immune-checkpoint-therapy', 'immune-checkpoint-inhibitors'),
    ('llm', 'large-language-models'),
    ('biomarker', 'biomarkers'),
    ('multiplex-imaging', 'multiplexed-imaging'),
    ('multiplex-tissue-imaging', 'multiplexed-imaging'),
    ('multiomics', 'multi-omics'),
    ('pan-cancer-analysis', 'pan-cancer'),
    ('clinical-trials', 'clinical-trial'),
    ('antibody-drug-conjugate', 'antibody-drug-conjugates'),
    ('multi-modal-learning', 'multimodal-learning'),
    ('immune-escape', 'immune-evasion'),
    ('immune-checkpoint-inhibitor', 'immune-checkpoint-inhibitors'),
    ('immune-checkpoint-inhibition', 'immune-checkpoint-inhibitors'),
    ('checkpoint-inhibitors', 'immune-checkpoint-inhibitors'),
    ('checkpoint-inhibitor', 'immune-checkpoint-inhibitors'),
    ('graph-neural-network', 'graph-neural-networks'),
    ('therapy-resistance', 'drug-resistance'),
    ('treatment-resistance', 'drug-resistance'),
    ('therapeutic-resistance', 'drug-resistance'),
    ('mouse-models', 'mouse-model'),
    ('multiplexed-immunofluorescence', 'multiplex-immunofluorescence'),
    ('prognostic-biomarker', 'prognostic-biomarkers'),
    ('cell-cell-interactions', 'cell-cell-communication'),
    ('cell-cell-interaction', 'cell-cell-communication'),
    ('xenium-in-situ', 'xenium'),
    ('ai-agent', 'ai-agents'),
    ('crispr-screening', 'crispr-screen'),
    ('cancer-evolution', 'tumor-evolution'),
    ('spatial-domain-detection', 'spatial-domain-identification'),
    ('copy-number-alteration', 'copy-number-alterations'),
    ('generative-models', 'generative-model'),
    ('generative-modeling', 'generative-model'),
    ('deep-generative-model', 'generative-model'),
    ('deep-generative-models', 'generative-model'),
    ('multi-modal-integration', 'multimodal-integration'),
    ('multimodal-data-integration', 'multimodal-integration'),
    ('multimodal-fusion', 'multimodal-integration'),
    ('chemoresistance', 'chemotherapy-resistance'),
    ('cytof', 'mass-cytometry'),
    ('he-image-analysis', 'h&e-imaging'),
    ('h&e-image-analysis', 'h&e-imaging'),
    ('nsclc', 'non-small-cell-lung-cancer'),
    ('vision-language-models', 'vision-language-model'),
    ('cdk4-6-inhibitors', 'cdk4-6-inhibitor'),
    ('cdk4/6-inhibitor', 'cdk4-6-inhibitor'),
    ('lightsheet-microscopy', 'light-sheet-microscopy'),
    ('diffusion-model', 'diffusion-models'),
    ('immune-cell-infiltration', 'immune-infiltration'),
    ('cancer-therapy', 'cancer-therapeutics'),
    ('cancer-treatment', 'cancer-therapeutics'),
    ('cancer-detection', 'cancer-diagnosis'),
    ('software-tools', 'software-tool'),
    ('single-nucleus-transcriptomics', 'single-nucleus-rna-seq'),
    ('cell-typing', 'cell-type-annotation'),
    ('cell-type-classification', 'cell-type-annotation'),
    ('cell-classification', 'cell-type-annotation'),
    ('neurodegenerative-disease', 'neurodegeneration'),
    ('pathology-foundation-models', 'pathology-foundation-model'),
    ('brain-metastases', 'brain-metastasis'),
    ('tissue-microarrays', 'tissue-microarray'),
    ('anti-tumor-immunity', 'antitumor-immunity'),
    ('real-world-data', 'real-world-evidence'),
    ('real-world-study', 'real-world-evidence'),
    ('car-t-cell-therapy', 'car-t-therapy'),
    ('residual-disease', 'minimal-residual-disease'),
    ('cancer-dormancy', 'tumor-dormancy'),
    ('intra-tumoral-heterogeneity', 'intratumor-heterogeneity'),
    ('dimension-reduction', 'dimensionality-reduction'),
    ('cranial-bone-marrow', 'skull-bone-marrow'),
    ('immunosurveillance', 'immune-surveillance'),
    ('virtual-spatial-transcriptomics', 'spatial-transcriptomics-prediction'),
    ('protein-language-models', 'protein-language-model'),
    ('gut-microbiota', 'gut-microbiome'),
    ('image-translation', 'image-to-image-translation'),
    ('immunoprofiling', 'immune-profiling'),
    ('cancer-metabolism', 'tumor-metabolism'),
    ('precancerous-lesions', 'premalignant-lesions'),
    ('therapeutic-target-discovery', 'drug-target-discovery'),
    ('spatially-aware-clustering', 'spatial-clustering'),
    ('immunopeptidome', 'immunopeptidomics'),
    ('vegf-c-signaling', 'vegf-c'),
    ('scientific-integrity', 'research-integrity'),
    ('cancer-classification', 'tumor-classification'),
    ('dependency-mapping', 'gene-dependency-mapping'),
    ('intratumor-microbiome', 'tumor-microbiome'),
    ('bioinformatics-tools', 'bioinformatics-tool'),
    ('knowledge-distillation', 'model-distillation'),
    ('trajectory-analysis', 'trajectory-inference'),
    ('immune-suppression', 'immunosuppression'),
    ('spatial-single-cell-analysis', 'single-cell-spatial-analysis'),
    ('single-cell-spatial', 'single-cell-spatial-analysis'),
    ('chromosome-instability', 'chromosomal-instability'),
    ('protocols', 'protocol'),
    ('parp-inhibition', 'parp-inhibitors'),
    ('graph-attention-network', 'graph-attention-networks');

insert into public.tag_merge_backup (batch, tbl, row_id, old_tags)
select '2026-10-10', 'papers', id, tags from public.papers
 where tags is distinct from public.clean_tags(tags)
union all
select '2026-10-10', 'paper_posts', id, tags from public.paper_posts
 where tags is distinct from public.clean_tags(tags)
union all
select '2026-10-10', 'removed_posts', id, tags from public.removed_posts
 where tags is distinct from public.clean_tags(tags)
union all
select '2026-10-10', 'profiles', id, interests from public.profiles
 where interests is distinct from public.clean_tags(interests);

select * from public.apply_tag_cleanup();
