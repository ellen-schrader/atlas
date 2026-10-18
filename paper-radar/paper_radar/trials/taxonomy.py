"""The breast cancer taxonomy the MVP filters and colours trials by.

Fixed in code for now (see the plan): one module, so a second disease area can
be added later. The keys are what's stored; the labels are what people see.
Keep in step with:
  * the check constraints in supabase/migrations/20261019170000_trial_facts.sql
  * web/src/lib/trials.ts
"""

from __future__ import annotations

SETTINGS: dict[str, str] = {
    "neoadjuvant": "Neoadjuvant",
    "adjuvant": "Adjuvant",
    "metastatic": "Metastatic",
}

PATIENT_GROUPS: dict[str, str] = {
    "tnbc": "TNBC",
    "hr_pos_her2_neg": "HR+/HER2−",
    "her2_pos": "HER2+",
    "her2_low": "HER2-low",
    "gbrca": "gBRCA",
}

THERAPY_CLASSES: dict[str, str] = {
    "immunotherapy": "Immunotherapy",
    "adc": "ADC",
    "cdk46": "CDK4/6 inhibitor",
    "parp": "PARP inhibitor",
    "her2_targeted": "HER2-targeted",
    "other_targeted": "Other targeted",
    "endocrine": "Endocrine",
    "chemotherapy": "Chemotherapy",
}
