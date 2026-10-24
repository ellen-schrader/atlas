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
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from paper_radar.ingest.metadata import PaperMetadata, fetch_metadata
from paper_radar.ingest.urls import norm_doi
from paper_radar.search import query as q
from paper_radar.search import sources
from paper_radar.search.sources import Hit, SourceError

from .deps import require_feature, require_token
from .ratelimit import PerUserRateLimiter
from .supa import service_client

log = logging.getLogger(__name__)

FEATURE = "saved_searches"
SOURCES = ("pubmed", "biorxiv", "arxiv")
MAX_SEARCHES = 10  # per person per lab
MAX_PER_CALL = 50  # suggestions imported or dismissed in one request
WINDOW_DAYS = 7  # what a first run, and the preview, look back over
OVERLAP_DAYS = 3  # later runs reach back past the last one: arXiv announces a
# Thursday submission on Sunday evening, and PubMed indexes late too
RETRY_RUNS = 3  # a failing search is tried daily this many times, then weekly
IMPORT_STUCK_AFTER = timedelta(hours=1)  # an import still running after this was lost

router = APIRouter(prefix="/saved-searches", tags=["saved-searches"])

_SEARCH_COLUMNS = (
    "id, user_id, team_id, name, query, sources, active, last_run_at, last_error, failed_runs"
)
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
    # missed days too (what the others found is filed already, and not twice).
    # One that keeps failing -- a query PubMed rejects -- goes back to weekly.
    failed_runs = (search.get("failed_runs") or 0) + 1 if error else 0
    changes: dict = {"last_error": error or None, "failed_runs": failed_runs}
    if failed_runs == 0 or failed_runs >= RETRY_RUNS:
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
    """Move the caller's own pending suggestions among ``ids`` to ``status``
    ('importing' or 'dismissed') and return them with their papers. Others'
    ids, and answered ones, are ignored."""
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
    return with_candidates(svc, rows)


def with_candidates(svc, rows: list[dict]) -> list[dict]:
    """``rows`` with each one's candidate paper under "candidate"."""
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


def _import_meta(c: dict) -> PaperMetadata:
    """What to store: the full lookup posting a link does (venue, keywords,
    preprint links), else the source's own record. The source's DOI and
    abstract fill gaps in the lookup, so later DOI matching finds the paper."""
    try:
        meta = fetch_metadata(c["url"])
    except Exception as exc:
        log.info("lookup of %s failed, using the source's record: %s", c["url"], exc)
        return _meta_of(c)
    if not meta.title:
        return _meta_of(c)
    if not meta.doi:
        meta.doi = norm_doi(c.get("doi"))
    if not meta.abstract:
        meta.abstract = c.get("abstract")
    return meta


def import_taken(team_id: str, user_id: str, taken: list[dict]) -> None:
    """Background: add each taken ('importing') suggestion's paper to the lab as
    the person, then mark it imported. One that fails goes back to pending, to
    be tried again; one this never reaches (the machine stopped) is retried by
    the daily job (:func:`retry_stuck_imports`)."""
    from .lab_papers import add_to_lab  # lab_papers imports app, which imports this

    svc = service_client()
    for row in taken:
        c = row.get("candidate")
        if not c:
            continue
        try:
            added = add_to_lab(
                svc, team_id, _import_meta(c), c["url"], source="saved_search", posted_by=user_id
            )
            svc.table("search_suggestions").update(
                {"status": "imported", "paper_id": added.paper_id}
            ).eq("id", row["id"]).execute()
        except Exception as exc:
            log.warning("importing suggestion %s for team %s failed: %s", row["id"], team_id, exc)
            svc.table("search_suggestions").update({"status": "pending", "decided_at": None}).eq(
                "id", row["id"]
            ).execute()


def retry_stuck_imports(svc, now: datetime) -> int:
    """Finish imports the API never got to (it stopped mid-import). Returns how many."""
    rows = (
        svc.table("search_suggestions")
        .select("id, user_id, team_id, candidate_id")
        .eq("status", "importing")
        .lt("decided_at", (now - IMPORT_STUCK_AFTER).isoformat())
        .limit(500)
        .execute()
        .data
        or []
    )
    by_owner: dict[tuple[str, str], list[dict]] = {}
    for row in with_candidates(svc, rows):
        by_owner.setdefault((row["team_id"], row["user_id"]), []).append(row)
    for (team_id, user_id), taken in by_owner.items():
        import_taken(team_id, user_id, taken)
    return len(rows)


# --- API -----------------------------------------------------------------------------------


def _require_feature(token: str, team_id: str) -> str:
    return require_feature(token, team_id, FEATURE)


# Each preview or run-now reaches PubMed and arXiv; arXiv asks for 3 s between calls.
_run_limiter = PerUserRateLimiter(
    20, 3600.0, lambda: HTTPException(status_code=429, detail="Too many searches. Try later.")
)


class Refused(Exception):
    """A request this module turns down, in words for the person; ``status`` is
    the HTTP status the API answers with."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


@contextmanager
def _as_http():
    try:
        yield
    except Refused as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


def checked_query(query: str) -> str:
    """The query, stripped, or Refused saying what is wrong with it in words (a
    pydantic validator would answer with a list the web app cannot show)."""
    query = query.strip()
    if not query:
        raise Refused("The query is empty.")
    if len(query) > 2000:
        raise Refused("The query is too long (2,000 characters at most).")
    try:
        q.parse(query)
    except q.QueryError as exc:
        raise Refused(str(exc)) from exc
    return query


def checked_sources(picked: Iterable[str]) -> list[str]:
    picked = [s for s in SOURCES if s in set(picked)]  # canonical order, no repeats
    if not picked:
        raise Refused("Pick at least one of: PubMed, bioRxiv/medRxiv, arXiv.")
    return picked


def own_searches(svc, user_id: str, team_id: str) -> list[dict]:
    """The person's searches in this lab, oldest first, each with how many of
    its suggestions are waiting (under "pending")."""
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
    return [{**r, "pending": counts.get(r["id"], 0)} for r in rows]


def new_search(
    svc, user_id: str, team_id: str, name: str, query: str, picked: Iterable[str]
) -> dict:
    """Save a search for the person (checked; Refused if not). The caller runs it."""
    name = " ".join(name.split())
    if not name or len(name) > 120:
        raise Refused("Give the search a name of up to 120 characters.")
    query, picked = checked_query(query), checked_sources(picked)
    have = (
        svc.table("saved_searches")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("team_id", team_id)
        .execute()
        .count
        or 0
    )
    if have >= MAX_SEARCHES:
        raise Refused(f"You have {MAX_SEARCHES} saved searches; delete one first.", 409)
    return (
        svc.table("saved_searches")
        .insert(
            {
                "user_id": user_id,
                "team_id": team_id,
                "name": name,
                "query": query,
                "sources": picked,
            }
        )
        .execute()
        .data[0]
    )


def preview_results(svc, team_id: str, query: str, picked: list[str]) -> list[SourceResult]:
    """What a (checked) query finds over the past week, per source, with the
    first ten papers of each marked if the lab has them."""
    since, until = window(None, date.today())
    feed = rxiv_feed(svc, since) if "biorxiv" in picked else None
    found, errors = run_query(query, picked, since, until, feed=feed)
    out = []
    for source in picked:
        hits = _dedupe(found.get(source, []))
        in_lab = keys_in_lab(svc, team_id, hits[:10])
        out.append(
            SourceResult(
                source=source,
                count=len(hits),
                papers=[_paper_out(h, h.key in in_lab) for h in hits[:10]],
                error=errors.get(source),
            )
        )
    return out


def pending_by_ids(svc, user_id: str, team_id: str, ids: list[str]) -> list[dict]:
    """The person's own pending suggestions among ``ids``, with their papers."""
    rows = (
        svc.table("search_suggestions")
        .select("id, candidate_id, saved_search_id")
        .in_("id", ids)
        .eq("user_id", user_id)
        .eq("team_id", team_id)
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    return with_candidates(svc, rows)


class SearchIn(BaseModel):
    team_id: UUID
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=2000)
    sources: list[str] = Field(default_factory=lambda: list(SOURCES), max_length=10)


class SearchPatch(BaseModel):
    team_id: UUID
    name: str | None = Field(default=None, min_length=1, max_length=120)
    query: str | None = Field(default=None, min_length=1, max_length=2000)
    sources: list[str] | None = Field(default=None, max_length=10)
    active: bool | None = None


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
    team_id: UUID
    query: str = Field(min_length=1, max_length=2000)
    sources: list[str] = Field(default_factory=lambda: list(SOURCES), max_length=10)


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
    team_id: UUID
    ids: list[UUID] = Field(min_length=1, max_length=MAX_PER_CALL)


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


def run_now(search: dict) -> None:
    """Background: a new or changed search runs at once rather than next week.
    Never raises."""
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
def my_searches(team_id: UUID, token: str = Depends(require_token)) -> list[SavedSearch]:
    team = str(team_id)
    user_id = _require_feature(token, team)
    return [_search_out(r, r["pending"]) for r in own_searches(service_client(), user_id, team)]


def _search_out(row: dict, pending: int = 0) -> SavedSearch:
    return SavedSearch(
        **{k: row.get(k) for k in SavedSearch.model_fields if k != "pending"}, pending=pending
    )


@router.post("", response_model=SavedSearch, status_code=201)
def create_search(
    req: SearchIn, background: BackgroundTasks, token: str = Depends(require_token)
) -> SavedSearch:
    team = str(req.team_id)
    user_id = _require_feature(token, team)
    svc = service_client()
    with _as_http():
        checked_query(req.query)
        checked_sources(req.sources)
        _run_limiter.check(user_id)
        row = new_search(svc, user_id, team, req.name, req.query, req.sources)
    background.add_task(run_now, row)
    return _search_out(row)


@router.patch("/{search_id}", response_model=SavedSearch)
def update_search(
    search_id: UUID,
    req: SearchPatch,
    background: BackgroundTasks,
    token: str = Depends(require_token),
) -> SavedSearch:
    team = str(req.team_id)
    user_id = _require_feature(token, team)
    svc = service_client()
    current = _own_search(svc, str(search_id), user_id, team)
    changes: dict = {}
    if req.name is not None:
        changes["name"] = req.name.strip()
    with _as_http():
        if req.query is not None:
            changes["query"] = checked_query(req.query)
        if req.sources is not None:
            changes["sources"] = checked_sources(req.sources)
    if req.active is not None:
        changes["active"] = req.active
    # A changed query or source list starts again from a week back.
    rerun = any(changes.get(k, current[k]) != current[k] for k in ("query", "sources"))
    if rerun:
        _run_limiter.check(user_id)
        changes.update(last_run_at=None, last_error=None, failed_runs=0)
    changes["updated_at"] = datetime.now(UTC).isoformat()
    row = (
        svc.table("saved_searches")
        .update(changes)
        .eq("id", str(search_id))
        .eq("user_id", user_id)
        .execute()
        .data[0]
    )
    if rerun and row["active"]:
        background.add_task(run_now, row)
    return _search_out(row)


@router.delete("/{search_id}", status_code=204)
def delete_search(search_id: UUID, team_id: UUID, token: str = Depends(require_token)) -> None:
    user_id = _require_feature(token, str(team_id))
    svc = service_client()
    _own_search(svc, str(search_id), user_id, str(team_id))
    svc.table("saved_searches").delete().eq("id", str(search_id)).eq("user_id", user_id).execute()


@router.post("/preview", response_model=list[SourceResult])
def preview(req: PreviewIn, token: str = Depends(require_token)) -> list[SourceResult]:
    """What the query finds over the past week, before it is saved."""
    team = str(req.team_id)
    user_id = _require_feature(token, team)
    with _as_http():
        query, picked = checked_query(req.query), checked_sources(req.sources)
    _run_limiter.check(user_id)
    return preview_results(service_client(), team, query, picked)


@router.get("/suggestions", response_model=list[Suggestion])
def my_suggestions(team_id: UUID, token: str = Depends(require_token)) -> list[Suggestion]:
    user_id = _require_feature(token, str(team_id))
    rows = list_suggestions(service_client(), user_id, str(team_id))
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
    team = str(req.team_id)
    user_id = _require_feature(token, team)
    ids = [str(i) for i in req.ids]
    taken = take_pending(service_client(), user_id, team, ids, "importing")
    if taken:
        background.add_task(import_taken, team, user_id, taken)
    return Decided(count=len(taken))


@router.post("/suggestions/dismiss", response_model=Decided)
def dismiss_suggestions(req: Decide, token: str = Depends(require_token)) -> Decided:
    team = str(req.team_id)
    user_id = _require_feature(token, team)
    taken = take_pending(service_client(), user_id, team, [str(i) for i in req.ids], "dismissed")
    return Decided(count=len(taken))
