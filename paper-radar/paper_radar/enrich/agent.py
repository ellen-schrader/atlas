"""Enrichment agent -- STUB.

This is intentionally left unimplemented. The signatures and docstrings define
the contract; fill in the bodies yourself.

Intended flow:
    raw text (from the paper URL / PDF) -> Claude -> PaperEnrichment

Use the ``anthropic`` SDK with structured output (tool use / JSON schema derived
from ``PaperEnrichment``). Read the API key and model name from ``get_settings()``;
never hardcode credentials.
"""

from __future__ import annotations

from ..config import Settings, get_settings
from ..models import Paper, PaperEnrichment


def build_enrichment_prompt(paper: Paper, source_text: str) -> str:
    """Build the user prompt for enriching one paper.

    Args:
        paper: The paper row (has at least a URL; may have partial metadata).
        source_text: Extracted text/abstract to ground the enrichment.

    Returns:
        The prompt string to send to Claude.
    """
    # TODO: describe the lab's focus, ask for a concise summary, domain tags,
    # and any code/data repository URLs mentioned in the source text.
    raise NotImplementedError


def enrich_paper(
    paper: Paper,
    source_text: str,
    *,
    settings: Settings | None = None,
) -> PaperEnrichment:
    """Call Claude to produce a structured :class:`PaperEnrichment` for ``paper``.

    Args:
        paper: The paper to enrich.
        source_text: Grounding text (abstract, first pages, etc.).
        settings: Optional settings override; defaults to ``get_settings()``.

    Returns:
        A populated ``PaperEnrichment``.
    """
    settings = settings or get_settings()
    # TODO: instantiate anthropic.Anthropic(api_key=settings.anthropic_api_key),
    # call messages.create(model=settings.anthropic_model, ...) with a tool whose
    # input_schema == PaperEnrichment.model_json_schema(), then validate the
    # tool-use payload back into PaperEnrichment.
    raise NotImplementedError


def apply_enrichment(paper: Paper, enrichment: PaperEnrichment) -> Paper:
    """Copy non-empty enrichment fields onto ``paper`` in place and return it."""
    # TODO: for each field in enrichment, overwrite paper.<field> when the
    # enrichment value is set (and, for lists, non-empty).
    raise NotImplementedError
