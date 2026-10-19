"""What Claude extracts from a trial's papers: the shape of trial_facts.extraction.

Mirrors what the mock-up's trial and compare views show (clinical-trials-brief/
MVP2): PICO, design, the treatment schedule, endpoints, adverse events, who was
enrolled (by baseline dimension, with what the protocol allowed) and the
"differs" items that make trials hard to compare. Every group of values names
its source (document, and where in it), so a lab member can check it.

A value the papers don't report is null, never a guess.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Source(BaseModel):
    doc: int = Field(description="1-based number of the document, as listed in the request")
    where: str = Field(description='Where in it: "Table 1", "Figure 2A", "Methods", "Abstract"')
    page: str | None = Field(default=None, description="Page number, if the document has pages")
    anchor: str | None = Field(
        default=None,
        description="In a full-text document, the id shown on the table, figure or section "
        'the values come from ("Tab1" from "[Table id=Tab1]", "Sec3" from "[id=Sec3]")',
    )
    quote: str | None = Field(
        default=None,
        description="A few words copied exactly from that place that show the main value: "
        'a table row as shown ("ECOG PS | 0 | 157 (95) | 154 (92)") or part of a sentence; '
        "at most 25 words",
    )

    # Both only help find the value: a malformed one is dropped or cut, never
    # a reason to fail (and pay again for) the whole extraction.
    @field_validator("anchor")
    @classmethod
    def _plain_anchor(cls, v: str | None) -> str | None:
        if not v:
            return None
        m = re.fullmatch(r"\s*(\w[\w.-]{0,63})\s*", v) or re.search(r"\bid=(\w[\w.-]{0,63})", v)
        return m.group(1) if m else None

    @field_validator("quote")
    @classmethod
    def _short_quote(cls, v: str | None) -> str | None:
        return v.strip()[:300] or None if v else None


class Pico(BaseModel):
    population: str
    intervention: str
    comparator: str
    outcome: str


class Design(BaseModel):
    phase: str | None = Field(description='"Phase III"')
    randomisation_ratio: str | None = Field(description='"2:1"; null if not randomised')
    blinding: Literal["open-label", "single-blind", "double-blind"] | None
    analysis_population: str | None = Field(description='"Intention-to-treat", "modified ITT"')
    data_cutoff: str | None = Field(description='Data cut-off of the main analysis, "March 2024"')
    source: Source | None


class Arm(BaseModel):
    role: Literal["experimental", "control"]
    label: str = Field(description='"Pembrolizumab + chemotherapy"')
    n_randomised: int | None
    n_analysed: int | None
    source: Source | None


PhaseKind = Literal[
    "chemotherapy",
    "surgery",
    "radiotherapy",
    "immunotherapy",
    "adc",
    "targeted",
    "endocrine",
    "observation",
    "other",
]


class Phase(BaseModel):
    """One block of the treatment schedule, in order, shared by both arms."""

    label: str = Field(description='"Paclitaxel + carboplatin", "Surgery", "Adjuvant"')
    kind: PhaseKind = Field(description="What both arms receive in this block")
    weeks: float | None = Field(description="Length in weeks (cycles × cycle length)")
    experimental_add: str | None = Field(
        description='Given on top in the experimental arm only, e.g. "Pembrolizumab"; null if none'
    )
    control_add: str | None = Field(
        description='Given on top in the control arm only, usually "Placebo"; null if none'
    )


class Endpoint(BaseModel):
    name: str = Field(description='"pCR", "EFS", "OS", "iDFS", "PFS"')
    role: Literal["primary", "co_primary", "key_secondary", "secondary", "exploratory"]
    kind: Literal["rate", "hazard_ratio"]
    definition: str | None = Field(description='pCR "ypT0/is ypN0"; how events were counted')
    timepoint: str | None = Field(description='Landmark of the rates, "at 5 years"')
    exp_value: float | None = Field(description="Experimental arm, percent")
    ctrl_value: float | None = Field(description="Control arm, percent")
    difference: float | None = Field(description="Percentage points, experimental minus control")
    difference_ci_low: float | None
    difference_ci_high: float | None
    hr: float | None
    hr_ci_low: float | None
    hr_ci_high: float | None
    events: int | None
    median_followup_months: float | None
    p_value: str | None
    source: Source | None


class AdverseEvent(BaseModel):
    label: str = Field(description='"Grade ≥3", "Immune-related", "Discontinued for AEs"')
    exp_pct: float | None
    ctrl_pct: float | None
    source: Source | None


# The categories each baseline dimension is reported in. Claude maps the
# paper's own categories onto these (e.g. "N2" and "N3" into "N2–3").
DIMENSIONS: dict[str, tuple[str, list[str]]] = {
    "t_stage": ("Clinical T stage", ["T1", "T2", "T3", "T4"]),
    "nodal_status": ("Nodal status", ["N0", "N1", "N2–3"]),
    "overall_stage": ("Overall stage", ["I", "II", "III"]),
    "ecog": ("ECOG", ["0", "1", "2+"]),
    "tils": ("Stromal TILs", ["High", "Int", "Low"]),
    "age": ("Age", ["<40", "40–49", "50–64", "≥65"]),
    "pdl1": ("PD-L1", ["Positive", "Negative"]),
    "menopausal_status": ("Menopausal status", ["Pre", "Post"]),
}

DimensionKey = Literal[
    "t_stage", "nodal_status", "overall_stage", "ecog", "tils", "age", "pdl1", "menopausal_status"
]


class Category(BaseModel):
    label: str = Field(description="One of the dimension's categories, exactly as listed")
    eligibility: Literal["allowed", "conditional", "not_allowed", "unknown"] = Field(
        description="What the protocol's eligibility criteria say about this category"
    )
    condition: str | None = Field(description='For "conditional": "T1c only with N1–2"')
    overall_pct: float | None = Field(description="Percent of all randomised patients")
    exp_pct: float | None
    ctrl_pct: float | None


class Dimension(BaseModel):
    key: DimensionKey
    categories: list[Category]
    not_reported_pct: float | None = Field(description='Percent "unknown" / "missing"')
    assay: str | None = Field(description='For PD-L1: "22C3 (CPS ≥1)"')
    source: Source | None


class Enrolment(BaseModel):
    n_screened: int | None
    n_randomised: int | None
    n_analysed: int | None
    dimensions: list[Dimension] = Field(description="Only dimensions the papers report")
    source: Source | None


ContextKey = Literal[
    "pcr_definition",
    "pathology_review",
    "efs_events_counted",
    "followup",
    "post_surgery_therapy",
    "enrolment_years",
    "region",
    "pdl1_assay",
]

CONTEXT_LABELS: dict[str, str] = {
    "pcr_definition": "pCR definition",
    "pathology_review": "Pathology review",
    "efs_events_counted": "EFS events counted",
    "followup": "Follow-up at cut-off",
    "post_surgery_therapy": "Therapy after surgery",
    "enrolment_years": "Enrolment years",
    "region": "Region",
    "pdl1_assay": "PD-L1 assay",
}


class ContextItem(BaseModel):
    """Details that decide whether this trial can be compared with another."""

    key: ContextKey
    value: str = Field(description='Short: "Central", "2017–2018", "Capecitabine allowed"')
    source: Source | None


class Extraction(BaseModel):
    pico: Pico
    design: Design
    arms: list[Arm]
    schedule: list[Phase] = Field(description="The treatment schedule in order; empty if unclear")
    endpoints: list[Endpoint]
    adverse_events: list[AdverseEvent]
    enrolment: Enrolment
    context: list[ContextItem]
    caveats: str | None = Field(
        description="Anything a reader must know: values converted from counts, conflicting "
        "numbers between documents, analyses that aren't the main one"
    )
