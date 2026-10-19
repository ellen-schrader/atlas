"""ClinicalTrials.gov API v2: fetch a trial by NCT ID, or search for one.

Free and keyless. Every request goes to one fixed host with an NCT ID we have
validated or a URL-encoded search term, so unlike paper ingest there is no
caller-chosen URL to guard.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from paper_radar.contact import API_USER_AGENT

log = logging.getLogger(__name__)

BASE = "https://clinicaltrials.gov/api/v2/studies"
_TIMEOUT = 15.0
_UA = API_USER_AGENT
_MAX_BYTES = 5_000_000  # one study with results is a few hundred kB

NCT_RE = re.compile(r"\bNCT\s?(\d{8})\b", re.IGNORECASE)
_NCT_EXACT = re.compile(r"^NCT\d{8}$")


class RegistryError(Exception):
    """ClinicalTrials.gov could not be reached, or answered with something unusable."""


@dataclass
class TrialRecord:
    """The columns of public.trials, from one registry record."""

    nct_id: str
    title: str
    acronym: str | None = None
    official_title: str | None = None
    phases: list[str] = field(default_factory=list)
    status: str | None = None
    sponsor: str | None = None
    conditions: list[str] = field(default_factory=list)
    enrollment: int | None = None
    start_date: str | None = None
    completion_date: str | None = None
    has_results: bool = False
    registry: dict[str, Any] = field(default_factory=dict)
    registry_updated_at: str | None = None

    def row(self) -> dict[str, Any]:
        return {
            "nct_id": self.nct_id,
            "title": self.title,
            "acronym": self.acronym,
            "official_title": self.official_title,
            "phases": self.phases,
            "status": self.status,
            "sponsor": self.sponsor,
            "conditions": self.conditions,
            "enrollment": self.enrollment,
            "start_date": self.start_date,
            "completion_date": self.completion_date,
            "has_results": self.has_results,
            "registry": self.registry,
            "registry_updated_at": self.registry_updated_at,
            "breast_cancer": self.is_breast_cancer,
        }

    @property
    def is_breast_cancer(self) -> bool:
        """The MVP covers breast cancer only (see the plan)."""
        ident = self.registry.get("identificationModule") or {}
        keywords = (self.registry.get("conditionsModule") or {}).get("keywords") or []
        text = " ".join([*self.conditions, *keywords, self.title, ident.get("officialTitle") or ""])
        return "breast" in text.lower()


def normalise_nct(value: str) -> str | None:
    """'nct 03036488', 'NCT03036488' → 'NCT03036488'; anything else → None."""
    m = NCT_RE.fullmatch(value.strip())
    return f"NCT{m.group(1)}" if m else None


def find_nct_ids(text: str | None) -> list[str]:
    """Every NCT ID in `text`, normalised, in order of first appearance."""
    if not text:
        return []
    seen: dict[str, None] = {}
    for m in NCT_RE.finditer(text):
        seen.setdefault(f"NCT{m.group(1)}", None)
    return list(seen)


def _get_json(url: str) -> dict[str, Any] | None:
    """The JSON at `url`; None for a 404; RegistryError for anything else."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 — fixed https host
            body = resp.read(_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise RegistryError(f"ClinicalTrials.gov answered {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RegistryError(f"ClinicalTrials.gov unreachable: {exc}") from exc
    if len(body) > _MAX_BYTES:
        raise RegistryError("ClinicalTrials.gov response too large")
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise RegistryError("ClinicalTrials.gov sent invalid JSON") from exc
    if not isinstance(data, dict):
        raise RegistryError("ClinicalTrials.gov sent an unexpected shape")
    return data


def fetch(nct_id: str) -> TrialRecord | None:
    """The trial registered as `nct_id`, or None if there is no such trial."""
    if not _NCT_EXACT.match(nct_id):
        raise ValueError(f"not an NCT ID: {nct_id!r}")
    data = _get_json(f"{BASE}/{nct_id}?fields=protocolSection,hasResults")
    if data is None:
        return None
    return parse(data)


@dataclass
class SearchHit:
    nct_id: str
    title: str
    acronym: str | None
    phases: list[str]
    status: str | None
    conditions: list[str]


_SEARCH_FIELDS = "NCTId,BriefTitle,Acronym,SecondaryId,Phase,OverallStatus,Condition"


def search(query: str, *, limit: int = 8, condition: str | None = "breast") -> list[SearchHit]:
    """Trials matching `query`: an NCT ID, a trial name, or free text.

    Trial names ("KEYNOTE-522", "GeparNuevo") are usually acronyms or secondary
    IDs, which the registry's `query.id` matches exactly while its free-text
    search ranks them below unrelated trials. So the ID search goes first and
    free text only fills what's left.
    """
    query = query.strip()
    if not query:
        return []
    nct = normalise_nct(query)
    if nct:
        rec = fetch(nct)
        if rec is None or (condition == "breast" and not rec.is_breast_cancer):
            return []
        return [_hit_from_record(rec)]

    hits: dict[str, SearchHit] = {}
    for key in ("query.id", "query.term"):
        if len(hits) >= limit:
            break
        params = {key: query, "fields": _SEARCH_FIELDS, "pageSize": str(limit)}
        if condition:
            params["query.cond"] = condition
        data = _get_json(f"{BASE}?{urllib.parse.urlencode(params)}") or {}
        for study in data.get("studies") or []:
            hit = _hit_from_section(study.get("protocolSection") or {})
            if hit and hit.nct_id not in hits:
                hits[hit.nct_id] = hit
    return list(hits.values())[:limit]


def _hit_from_record(rec: TrialRecord) -> SearchHit:
    return SearchHit(rec.nct_id, rec.title, rec.acronym, rec.phases, rec.status, rec.conditions)


def _hit_from_section(section: dict[str, Any]) -> SearchHit | None:
    ident = section.get("identificationModule") or {}
    nct = ident.get("nctId")
    if not nct or not _NCT_EXACT.match(nct):
        return None
    return SearchHit(
        nct_id=nct,
        title=ident.get("briefTitle") or nct,
        acronym=pick_acronym(ident),
        phases=list((section.get("designModule") or {}).get("phases") or []),
        status=(section.get("statusModule") or {}).get("overallStatus"),
        conditions=list((section.get("conditionsModule") or {}).get("conditions") or []),
    )


# A trial name looks like "KEYNOTE-522", "monarchE", "IMpassion031": it has a
# run of at least four letters, which sponsor codes ("MK-3475-522") don't.
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[-‐][A-Za-z0-9]+)*$")
_LETTERS_RE = re.compile(r"[A-Za-z]{4,}")
_PAREN_RE = re.compile(r"\(([^()]+)\)")
# Words that sit in brackets in titles but aren't trial names.
_NOT_NAMES = {"tnbc", "her2", "pdl1", "pd-l1", "breast", "cancer", "study", "trial", "phase"}


def _looks_like_name(s: str) -> bool:
    s = s.strip()
    return (
        3 <= len(s) <= 40
        and bool(_NAME_RE.match(s))
        and bool(_LETTERS_RE.search(s))
        and s.lower() not in _NOT_NAMES
        and not s.upper().startswith("NCT")
    )


def pick_acronym(ident: dict[str, Any]) -> str | None:
    """The trial's short name: the registry's acronym, else a name in the
    title's brackets ("(MK-3475-522/KEYNOTE-522)"), else a secondary ID that
    looks like one. The lab can correct it later."""
    acronym = (ident.get("acronym") or "").strip()
    if acronym:
        return acronym
    for title in (ident.get("briefTitle"), ident.get("officialTitle")):
        for group in _PAREN_RE.findall(title or ""):
            for part in re.split(r"[/;,]", group):
                if _looks_like_name(part) and any(c.isdigit() for c in part):
                    return part.strip()
    for sec in ident.get("secondaryIdInfos") or []:
        sid = (sec.get("id") or "").strip()
        if sec.get("type") in (None, "OTHER") and _looks_like_name(sid) and not sid.isdigit():
            return sid
    return None


def parse(data: dict[str, Any]) -> TrialRecord:
    """A TrialRecord from the API's `{protocolSection, hasResults}` document."""
    section = data.get("protocolSection")
    if not isinstance(section, dict):
        raise RegistryError("record has no protocolSection")
    ident = section.get("identificationModule") or {}
    nct = ident.get("nctId")
    if not nct or not _NCT_EXACT.match(nct):
        raise RegistryError("record has no valid NCT ID")
    status = section.get("statusModule") or {}
    design = section.get("designModule") or {}
    enrollment = (design.get("enrollmentInfo") or {}).get("count")
    return TrialRecord(
        nct_id=nct,
        title=ident.get("briefTitle") or ident.get("officialTitle") or nct,
        acronym=pick_acronym(ident),
        official_title=ident.get("officialTitle"),
        phases=list(design.get("phases") or []),
        status=status.get("overallStatus"),
        sponsor=((section.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get(
            "name"
        ),
        conditions=list((section.get("conditionsModule") or {}).get("conditions") or []),
        enrollment=enrollment if isinstance(enrollment, int) else None,
        start_date=(status.get("startDateStruct") or {}).get("date"),
        completion_date=(status.get("completionDateStruct") or {}).get("date"),
        has_results=bool(data.get("hasResults")),
        registry=section,
        registry_updated_at=_full_date((status.get("lastUpdatePostDateStruct") or {}).get("date")),
    )


def _full_date(value: Any) -> str | None:
    """'2025-10-29' as is; a partial date ('2025-10') can't go in a date column."""
    return value if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None


def site_countries(locations: Any) -> list[tuple[str, int]]:
    """Countries the trial has sites in, with how many, most sites first, from
    the record's contactsLocationsModule.locations. Sites, not participants:
    the registry doesn't say how many each enrolled. Withdrawn sites (never
    opened) don't count."""
    counts: dict[str, int] = {}
    for loc in locations if isinstance(locations, list) else []:
        if not isinstance(loc, dict) or loc.get("status") == "WITHDRAWN":
            continue
        country = (loc.get("country") or "").strip()
        if country:
            counts[country] = counts.get(country, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
