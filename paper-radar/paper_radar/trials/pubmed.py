"""PubMed: which papers name a trial (its NCT ID as a secondary identifier).

NCBI E-utilities, keyless (3 requests a second), on a fixed host with an NCT ID
we validated. Used for the trial page's "N more papers on PubMed" hint.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from paper_radar.contact import API_USER_AGENT, CONTACT_EMAIL

from . import ctgov

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_TOOL = {"tool": "paper-radar", "email": CONTACT_EMAIL}
_UA = API_USER_AGENT
MAX_PAPERS = 100


class PubMedError(Exception):
    pass


@dataclass
class PubMedPaper:
    pmid: str
    title: str
    journal: str | None
    year: str | None
    doi: str | None


def _get(path: str, params: dict[str, str]) -> dict:
    url = f"{_EUTILS}/{path}?{urllib.parse.urlencode({**params, **_TOOL, 'retmode': 'json'})}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — fixed https host
            return json.loads(resp.read(5_000_000))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise PubMedError(str(exc)) from exc


def papers_naming(nct_id: str) -> tuple[int, list[PubMedPaper]]:
    """(how many PubMed records list this NCT ID, the first MAX_PAPERS of them)."""
    if ctgov.normalise_nct(nct_id) != nct_id:
        raise ValueError(f"not an NCT ID: {nct_id!r}")
    found = _get(
        "esearch.fcgi", {"db": "pubmed", "term": f"{nct_id}[si]", "retmax": str(MAX_PAPERS)}
    )
    result = found.get("esearchresult") or {}
    ids = [i for i in result.get("idlist") or [] if str(i).isdigit()]
    count = int(result.get("count") or 0)
    if not ids:
        return count, []
    summary = _get("esummary.fcgi", {"db": "pubmed", "id": ",".join(ids)}).get("result") or {}
    papers = []
    for pmid in ids:
        r = summary.get(pmid) or {}
        doi = next(
            (a.get("value") for a in r.get("articleids") or [] if a.get("idtype") == "doi"), None
        )
        papers.append(
            PubMedPaper(
                pmid=pmid,
                title=(r.get("title") or "").strip() or f"PubMed {pmid}",
                journal=r.get("source"),
                year=(r.get("pubdate") or "")[:4] or None,
                doi=doi.lower() if doi else None,
            )
        )
    return count, papers
