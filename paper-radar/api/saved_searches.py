"""Saved searches and their suggestions (issue #164).

A member saves a query and the sources to run it on; the weekly job
(api/saved_searches_run.py) files what is new as suggestions for them, and they
import the ones they want into the lab's library or dismiss the rest. Searches
and suggestions are personal; imports go to the shared library.

The tables have no grants for signed-in users (see the migration): everything
goes through here, which checks the feature and membership as the caller and
then reads and writes with the service role, like the trials tools. The
functions above the router take the service client, so the job and the Claude
tools use the same code.

Every endpoint answers 404 unless the feature is on for the caller in that lab.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from paper_radar.ingest.metadata import PaperMetadata, fetch_metadata
from paper_radar.ingest.urls import norm_doi
from paper_radar.search import query as q
from paper_radar.search import sources
from paper_radar.search.sources import Hit, SourceError

from .deps import require_token
from .ratelimit import PerUserRateLimiter
from .supa import get_user_id, service_client, user_client

log = logging.getLogger(__name__)

FEATURE = "saved_searches"
SOURCES = ("pubmed", "biorxiv", "arxiv")
MAX_SEARCHES = 10  # per person per lab
MAX_PER_CALL = 50  # suggestions imported or dismissed in one request
WINDOW_DAYS = 7  # what a first run, and the preview, look back over
OVERLAP_DAYS = 1  # later runs reach back past the last one, for late indexing

router = APIRouter(prefix="/saved-searches", tags=["saved-searches"])

_NOT_FOUND = "Not Found"  # FastAPI's own wording for an unknown route
_SEARCH_COLUMNS = "id, user_id, team_id, name, query, sources, active, last_run_at, last_error"
_CANDIDATE_COLUMNS = "key, source, doi, pmid, url, title, authors, venue, published_on, abstract"


# --- running a search ------------------------------------------------------------------


def window(last_run_at: str | None, today: date) -> tuple[date, date]:
    """The dates a run covers: a week the first time, then since the last run."""
    if last_run_at:
        last = datetime.fromisoformat(last_run_at).date()
        since = max(last - timedelta(days=OVERLAP_DAYS), today - timedelta(days=4 * WINDOW_DAYS))
    else:
        since = today - timedelta(days=WINDOW_DAYS)
    return since, today


_feed_cache: dict[date, tuple[float, list[dict]]] = {}
_feed_lock = threading.Lock()
_FEED_TTL = 600.0


def rxiv_feed(svc, since: date) -> list[dict]:
    """bioRxiv/medRxiv preprints posted since ``since``, from the daily copy.
    Cached for a few minutes: previews in a row would otherwise reload it."""
    with _feed_lock:
        hit = _feed_cache.get(since)
        if hit and time.monotonic() - hit[0] < _FEED_TTL:
            return hit[1]
    rows: list[dict] = []
    page = 1000
    while True:
        chunk = (
            svc.table("rxiv_feed")
            .select("doi, server, title, abstract, authors, posted_on")
            .gte("posted_on", since.isoformat())
            .order("doi")
            .range(len(rows), len(rows) + page - 1)
            .execute()
            .data
            or []
        )
        rows.extend(chunk)
        if len(chunk) < page:
            break
    with _feed_lock:
        _feed_cache.clear()
        _feed_cache[since] = (time.monotonic(), rows)
    return rows


def _rxiv_hits(node: q.Node, feed: Iterable[dict], since: date, until: date) -> list[Hit]:
    hits = []
    for row in feed:
        posted = row.get("posted_on") or ""
        if not (since.isoformat() <= posted <= until.isoformat()):
            continue
        authors = row.get("authors") or []
        doc = q.Doc(row["title"], row.get("abstract") or "", "; ".join(authors))
        if q.matches(node, doc):
            hits.append(
                Hit(
                    source=row["server"],
                    url=f"https://doi.org/{row['doi']}",
                    title=row["title"],
                    doi=row["doi"],
                    authors=authors,
                    venue="bioRxiv" if row["server"] == "biorxiv" else "medRxiv",
                    published_on=posted,
                    abstract=row.get("abstract"),
                )
            )
        if len(hits) >= sources.MAX_HITS:
            break
    return hits


def run_query(
    query: str,
    picked: Iterable[str],
    since: date,
    until: date,
    *,
    feed: Iterable[dict] | None,
    limit: int = sources.MAX_HITS,
) -> tuple[dict[str, list[Hit]], dict[str, str]]:
    """Run ``query`` on each picked source: (hits per source, error per source).

    A source failing does not stop the others. ``feed`` is the bioRxiv/medRxiv
    copy (:func:`rxiv_feed`); None skips those servers."""
    node = q.without_filters(q.parse(query))
    found: dict[str, list[Hit]] = {}
    errors: dict[str, str] = {}
    for source in picked:
        try:
            if source == "pubmed":
                found[source] = sources.search_pubmed(query, since, until, limit)
            elif node is None:
                found[source] = []  # only PubMed filters: nothing to look for here
            elif source == "arxiv":
                found[source] = sources.search_arxiv(q.to_arxiv(node), since, until, limit)
            elif source == "biorxiv" and feed is not None:
                found[source] = _rxiv_hits(node, feed, since, until)[:limit]
        except SourceError as exc:
            errors[source] = str(exc)
    return found, errors


def _dedupe(hits: Iterable[Hit]) -> list[Hit]:
    seen: dict[str, Hit] = {}
    for hit in hits:
        if hit.doi or hit.pmid:
            seen.setdefault(hit.key, hit)
    return list(seen.values())


def keys_in_lab(svc, team_id: str, hits: list[Hit]) -> set[str]:
    """The hits the lab already has, matched by DOI (directly or via an alias).

    Every source but a handful of PubMed records gives a DOI, and matching by
    URL would mean one lookup per hit."""
    by_doi = {h.doi: h.key for h in hits if h.doi}
    if not by_doi:
        return set()
    paper_of: dict[str, str] = {}
    dois = list(by_doi)
    for start in range(0, len(dois), 100):
        chunk = dois[start : start + 100]
        for row in svc.table("papers").select("id, doi").in_("doi", chunk).execute().data or []:
            paper_of[row["doi"]] = row["id"]
        rows = svc.table("paper_aliases").select("paper_id, doi").in_("doi", chunk).execute().data
        for row in rows or []:
            paper_of.setdefault(row["doi"], row["paper_id"])
    if not paper_of:
        return set()
    ids = list(set(paper_of.values()))
    posted: set[str] = set()
    for start in range(0, len(ids), 100):
        rows = (
            svc.table("paper_posts")
            .select("paper_id")
            .eq("team_id", team_id)
            .in_("paper_id", ids[start : start + 100])
            .execute()
            .data
        )
        posted |= {r["paper_id"] for r in rows or []}
    return {by_doi[d] for d, pid in paper_of.items() if pid in posted}


def file_hits(svc, search: dict, hits: list[Hit]) -> int:
    """File what the lab does not have as suggestions for the search's owner.
    Returns how many are new for them; one they dismissed stays dismissed."""
    hits = _dedupe(hits)
    in_lab = keys_in_lab(svc, search["team_id"], hits)
    hits = [h for h in hits if h.key not in in_lab]
    if not hits:
        return 0
    rows = [
        {
            "key": h.key,
            "source": h.source,
            "doi": h.doi,
            "pmid": h.pmid,
            "url": h.url,
            "title": h.title[:1000],
            "authors": h.authors[:100],
            "venue": h.venue,
            "published_on": h.published_on,
            "abstract": h.abstract,
        }
        for h in hits
    ]
    svc.table("search_candidates").upsert(rows, on_conflict="key", ignore_duplicates=True).execute()
    keys = [h.key for h in hits]
    ids: dict[str, str] = {}
    for start in range(0, len(keys), 100):
        found = (
            svc.table("search_candidates")
            .select("id, key")
            .in_("key", keys[start : start + 100])
            .execute()
            .data
        )
        ids.update({r["key"]: r["id"] for r in found or []})
    suggestions = [
        {
            "user_id": search["user_id"],
            "team_id": search["team_id"],
            "candidate_id": ids[k],
            "saved_search_id": search["id"],
        }
        for k in keys
        if k in ids
    ]
    if not suggestions:
        return 0
    added = (
        svc.table("search_suggestions")
        .upsert(suggestions, on_conflict="user_id,team_id,candidate_id", ignore_duplicates=True)
        .execute()
        .data
    )
    return len(added or [])


def run_saved_search(svc, search: dict, today: date, feed: list[dict] | None) -> tuple[int, str]:
    """Run one saved search and file its results: (new suggestions, error text)."""
    since, until = window(search.get("last_run_at"), today)
    try:
        found, errors = run_query(search["query"], search["sources"], since, until, feed=feed)
    except q.QueryError as exc:
        found, errors = {}, {"query": str(exc)}
    new = file_hits(svc, search, [h for hits in found.values() for h in hits])
    error = "; ".join(f"{s}: {e}" for s, e in errors.items())
    # A source that failed keeps the search due, so tomorrow's run covers its
    # missed days too; what the others found is filed already (and not twice).
    changes: dict = {"last_error": error or None}
    if not error:
        changes["last_run_at"] = datetime.now(UTC).isoformat()
    svc.table("saved_searches").update(changes).eq("id", search["id"]).execute()
    return new, error


# --- suggestions -------------------------------------------------------------------------


def list_suggestions(svc, user_id: str, team_id: str, limit: int = 300) -> list[dict]:
    """The person's pending suggestions in this lab, newest first. Ones the lab
    has gained another way since they were filed are marked and left out."""
    rows = (
        svc.table("search_suggestions")
        .select(
            f"id, created_at, saved_search_id, candidate:search_candidates({_CANDIDATE_COLUMNS})"
        )
        .eq("user_id", user_id)
        .eq("team_id", team_id)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    rows = [r for r in rows if r.get("candidate")]
    hits = [_hit_of(r["candidate"]) for r in rows]
    in_lab = keys_in_lab(svc, team_id, hits)
    stale = [r["id"] for r in rows if r["candidate"]["key"] in in_lab]
    if stale:
        svc.table("search_suggestions").update(
            {"status": "in_library", "decided_at": datetime.now(UTC).isoformat()}
        ).in_("id", stale).eq("status", "pending").execute()
    return [r for r in rows if r["id"] not in set(stale)]


def _hit_of(c: dict) -> Hit:
    return Hit(
        source=c["source"],
        url=c["url"],
        title=c["title"],
        doi=c.get("doi"),
        pmid=c.get("pmid"),
        authors=c.get("authors") or [],
        venue=c.get("venue"),
        published_on=c.get("published_on"),
        abstract=c.get("abstract"),
    )


def take_pending(svc, user_id: str, team_id: str, ids: list[str], status: str) -> list[dict]:
    """Move the caller's own pending suggestions among ``ids`` to ``status`` and
    return them with their papers. Others' ids, and answered ones, are ignored."""
    rows = (
        svc.table("search_suggestions")
        .update({"status": status, "decided_at": datetime.now(UTC).isoformat()})
        .in_("id", ids)
        .eq("user_id", user_id)
        .eq("team_id", team_id)
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    if not rows:
        return []
    cands = (
        svc.table("search_candidates")
        .select(f"id, {_CANDIDATE_COLUMNS}")
        .in_("id", list({r["candidate_id"] for r in rows}))
        .execute()
        .data
        or []
    )
    by_id = {c["id"]: c for c in cands}
    return [{**r, "candidate": by_id.get(r["candidate_id"])} for r in rows]


def _meta_of(c: dict) -> PaperMetadata:
    """The source's own record, for when the full lookup finds nothing better."""
    year = (c.get("published_on") or "")[:4]
    return PaperMetadata(
        url=c["url"],
        title=c["title"],
        authors=c.get("authors") or [],
        venue=c.get("venue"),
        year=int(year) if year.isdigit() else None,
        doi=norm_doi(c.get("doi")),
        abstract=c.get("abstract"),
        source={"pubmed": "pubmed", "arxiv": "arxiv"}.get(c["source"], "crossref"),
        is_preprint=c["source"] in ("biorxiv", "medrxiv", "arxiv"),
    )


def import_taken(team_id: str, user_id: str, taken: list[dict]) -> None:
    """Background: add each taken suggestion's paper to the lab as the person.

    The full metadata lookup (what posting a link does) runs first, for venue,
    keywords and preprint links; the source's record is the fallback. A paper
    that cannot be added goes back to pending, so it can be tried again."""
    from .lab_papers import add_to_lab  # lab_papers imports app, which imports this

    svc = service_client()
    for row in taken:
        c = row.get("candidate")
        if not c:
            continue
        try:
            meta = fetch_metadata(c["url"])
            if not meta.title:
                meta = _meta_of(c)
            added = add_to_lab(
                svc, team_id, meta, c["url"], source="saved_search", posted_by=user_id
            )
            svc.table("search_suggestions").update({"paper_id": added.paper_id}).eq(
                "id", row["id"]
            ).execute()
        except Exception as exc:
            log.warning("importing suggestion %s for team %s failed: %s", row["id"], team_id, exc)
            svc.table("search_suggestions").update({"status": "pending", "decided_at": None}).eq(
                "id", row["id"]
            ).execute()


# --- API -----------------------------------------------------------------------------------


def _require_feature(token: str, team_id: str) -> str:
    """The caller's id, or 404 unless the feature is on for them in this lab.
    Asked as the caller, so has_feature() checks membership too."""
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    ok = user_client(token).rpc("has_feature", {"t": team_id, "f": FEATURE}).execute().data
    if ok is not True:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return user_id


# Each preview or run-now reaches PubMed and arXiv; arXiv asks for 3 s between calls.
_run_limiter = PerUserRateLimiter(
    20, 3600.0, lambda: HTTPException(status_code=429, detail="Too many searches. Try later.")
)


def _validate_query(query: str) -> str:
    query = query.strip()
    try:
        q.parse(query)
    except q.QueryError as exc:
        raise ValueError(str(exc)) from exc
    return query


def _validate_sources(picked: list[str]) -> list[str]:
    picked = [s for s in SOURCES if s in set(picked)]  # canonical order, no repeats
    if not picked:
        raise ValueError("Pick at least one of: PubMed, bioRxiv/medRxiv, arXiv.")
    return picked


class SearchIn(BaseModel):
    team_id: str
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=2000)
    sources: list[str] = Field(default_factory=lambda: list(SOURCES))

    _query = field_validator("query")(_validate_query)
    _sources = field_validator("sources")(_validate_sources)


class SearchPatch(BaseModel):
    team_id: str
    name: str | None = Field(default=None, min_length=1, max_length=120)
    query: str | None = Field(default=None, min_length=1, max_length=2000)
    sources: list[str] | None = None
    active: bool | None = None

    @field_validator("query")
    @classmethod
    def _query(cls, v: str | None) -> str | None:
        return None if v is None else _validate_query(v)

    @field_validator("sources")
    @classmethod
    def _sources(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _validate_sources(v)


class SavedSearch(BaseModel):
    id: str
    name: str
    query: str
    sources: list[str]
    active: bool
    last_run_at: str | None
    last_error: str | None
    pending: int = 0


class PreviewIn(BaseModel):
    team_id: str
    query: str = Field(min_length=1, max_length=2000)
    sources: list[str] = Field(default_factory=lambda: list(SOURCES))

    _query = field_validator("query")(_validate_query)
    _sources = field_validator("sources")(_validate_sources)


class PaperOut(BaseModel):
    source: str
    url: str
    title: str
    doi: str | None
    pmid: str | None
    authors: list[str]
    venue: str | None
    published_on: str | None
    abstract: str | None
    in_lab: bool = False


class SourceResult(BaseModel):
    source: str
    count: int
    papers: list[PaperOut]
    error: str | None = None


class Suggestion(BaseModel):
    id: str
    saved_search_id: str | None
    created_at: str
    paper: PaperOut


class Decide(BaseModel):
    team_id: str
    ids: list[str] = Field(min_length=1, max_length=MAX_PER_CALL)


class Decided(BaseModel):
    count: int


def _paper_out(c: dict | Hit, in_lab: bool = False) -> PaperOut:
    data = c if isinstance(c, dict) else c.__dict__
    return PaperOut(
        **{k: data.get(k) for k in PaperOut.model_fields if k not in ("authors", "in_lab")},
        authors=list(data.get("authors") or [])[:20],
        in_lab=in_lab,
    )


def _own_search(svc, search_id: str, user_id: str, team_id: str) -> dict:
    rows = (
        svc.table("saved_searches")
        .select(_SEARCH_COLUMNS)
        .eq("id", search_id)
        .eq("user_id", user_id)
        .eq("team_id", team_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="That search is not one of yours.")
    return rows[0]


def _run_now(search: dict) -> None:
    """Background: a new or changed search runs at once rather than next week."""
    svc = service_client()
    try:
        since, _ = window(None, date.today())
        new, error = run_saved_search(svc, search, date.today(), rxiv_feed(svc, since))
        log.info(
            "saved search %s: %d new suggestions; errors: %s", search["id"], new, error or "none"
        )
    except Exception as exc:
        log.warning("running saved search %s failed: %s", search["id"], exc)


@router.get("", response_model=list[SavedSearch])
def my_searches(team_id: str, token: str = Depends(require_token)) -> list[SavedSearch]:
    user_id = _require_feature(token, team_id)
    svc = service_client()
    rows = (
        svc.table("saved_searches")
        .select(_SEARCH_COLUMNS)
        .eq("user_id", user_id)
        .eq("team_id", team_id)
        .order("created_at")
        .execute()
        .data
        or []
    )
    pending = (
        svc.table("search_suggestions")
        .select("saved_search_id")
        .eq("user_id", user_id)
        .eq("team_id", team_id)
        .eq("status", "pending")
        .limit(5000)
        .execute()
        .data
        or []
    )
    counts: dict[str, int] = {}
    for p in pending:
        counts[p["saved_search_id"]] = counts.get(p["saved_search_id"], 0) + 1
    return [SavedSearch(**r, pending=counts.get(r["id"], 0)) for r in rows]


@router.post("", response_model=SavedSearch, status_code=201)
def create_search(
    req: SearchIn, background: BackgroundTasks, token: str = Depends(require_token)
) -> SavedSearch:
    user_id = _require_feature(token, req.team_id)
    svc = service_client()
    have = (
        svc.table("saved_searches")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("team_id", req.team_id)
        .execute()
        .count
        or 0
    )
    if have >= MAX_SEARCHES:
        raise HTTPException(
            status_code=409, detail=f"You have {MAX_SEARCHES} saved searches; delete one first."
        )
    _run_limiter.check(user_id)
    row = (
        svc.table("saved_searches")
        .insert(
            {
                "user_id": user_id,
                "team_id": req.team_id,
                "name": req.name.strip(),
                "query": req.query,
                "sources": req.sources,
            }
        )
        .execute()
        .data[0]
    )
    background.add_task(_run_now, row)
    return SavedSearch(**{k: row.get(k) for k in SavedSearch.model_fields if k != "pending"})


@router.patch("/{search_id}", response_model=SavedSearch)
def update_search(
    search_id: str,
    req: SearchPatch,
    background: BackgroundTasks,
    token: str = Depends(require_token),
) -> SavedSearch:
    user_id = _require_feature(token, req.team_id)
    svc = service_client()
    current = _own_search(svc, search_id, user_id, req.team_id)
    changes = req.model_dump(exclude_unset=True, exclude={"team_id"})
    changes = {k: v for k, v in changes.items() if v is not None}
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    # A changed query or source list starts again from a week back.
    rerun = any(changes.get(k, current[k]) != current[k] for k in ("query", "sources"))
    if rerun:
        _run_limiter.check(user_id)
        changes["last_run_at"] = None
    changes["updated_at"] = datetime.now(UTC).isoformat()
    row = (
        svc.table("saved_searches")
        .update(changes)
        .eq("id", search_id)
        .eq("user_id", user_id)
        .execute()
        .data[0]
    )
    if rerun and row["active"]:
        background.add_task(_run_now, row)
    return SavedSearch(**{k: row.get(k) for k in SavedSearch.model_fields if k != "pending"})


@router.delete("/{search_id}", status_code=204)
def delete_search(search_id: str, team_id: str, token: str = Depends(require_token)) -> None:
    user_id = _require_feature(token, team_id)
    svc = service_client()
    _own_search(svc, search_id, user_id, team_id)
    svc.table("saved_searches").delete().eq("id", search_id).eq("user_id", user_id).execute()


@router.post("/preview", response_model=list[SourceResult])
def preview(req: PreviewIn, token: str = Depends(require_token)) -> list[SourceResult]:
    """What the query finds over the past week, before it is saved."""
    user_id = _require_feature(token, req.team_id)
    _run_limiter.check(user_id)
    svc = service_client()
    since, until = window(None, date.today())
    feed = rxiv_feed(svc, since) if "biorxiv" in req.sources else None
    found, errors = run_query(req.query, req.sources, since, until, feed=feed)
    out = []
    for source in req.sources:
        hits = _dedupe(found.get(source, []))
        in_lab = keys_in_lab(svc, req.team_id, hits[:10])
        out.append(
            SourceResult(
                source=source,
                count=len(hits),
                papers=[_paper_out(h, h.key in in_lab) for h in hits[:10]],
                error=errors.get(source),
            )
        )
    return out


@router.get("/suggestions", response_model=list[Suggestion])
def my_suggestions(team_id: str, token: str = Depends(require_token)) -> list[Suggestion]:
    user_id = _require_feature(token, team_id)
    rows = list_suggestions(service_client(), user_id, team_id)
    return [
        Suggestion(
            id=r["id"],
            saved_search_id=r.get("saved_search_id"),
            created_at=r["created_at"],
            paper=_paper_out(r["candidate"]),
        )
        for r in rows
    ]


@router.post("/suggestions/import", response_model=Decided)
def import_suggestions(
    req: Decide, background: BackgroundTasks, token: str = Depends(require_token)
) -> Decided:
    """Add the papers to the lab. They appear within a minute or so: each is
    looked up in full first, as posting a link is."""
    user_id = _require_feature(token, req.team_id)
    taken = take_pending(service_client(), user_id, req.team_id, req.ids, "imported")
    if taken:
        background.add_task(import_taken, req.team_id, user_id, taken)
    return Decided(count=len(taken))


@router.post("/suggestions/dismiss", response_model=Decided)
def dismiss_suggestions(req: Decide, token: str = Depends(require_token)) -> Decided:
    user_id = _require_feature(token, req.team_id)
    taken = take_pending(service_client(), user_id, req.team_id, req.ids, "dismissed")
    return Decided(count=len(taken))
