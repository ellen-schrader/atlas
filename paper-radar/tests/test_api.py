"""Smoke tests for the FastAPI service (offline — no network lookups)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api.app import app  # noqa: E402

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


AUTH = {"Authorization": "Bearer good"}


@pytest.fixture
def signed_in(monkeypatch):
    """/resolve needs an account now — it makes the server fetch a URL you chose."""
    import api.app as app_mod

    monkeypatch.setattr(app_mod, "get_user_id", lambda _t: "user-1")
    # A fresh limiter per test, so one test's calls can't 429 the next one's.
    monkeypatch.setattr(
        app_mod, "_resolve_limiter", app_mod._PerUserRateLimiter(max_events=30, window_seconds=60.0)
    )


def test_resolve_requires_a_bearer_token():
    """It used to be open to the internet: an unauthenticated caller could make the
    server GET any URL, which is a port scanner for whatever network it runs in."""
    resp = client.post("/resolve", json={"url": "https://arxiv.org/abs/2401.01234"})
    assert resp.status_code == 401


def test_resolve_recognizes_scheme_and_computes_dedup_key(signed_in):
    resp = client.post(
        "/resolve",
        json={"url": "https://arxiv.org/abs/2401.01234", "network": False},
        headers=AUTH,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "arxiv"
    assert data["url"] == "https://arxiv.org/abs/2401.01234"
    # url_norm drops scheme + www and is the dedup key (schemeless //host/path).
    assert data["url_norm"] == "//arxiv.org/abs/2401.01234"


@pytest.mark.parametrize(
    ("pasted", "coerced"),
    [
        # A bare DOI — what the add-paper box explicitly invites — used to die at
        # the http(s)-only guard with "Only http(s) links can be fetched."
        ("10.1038/s41586-020-2649-2", "https://doi.org/10.1038/s41586-020-2649-2"),
        ("doi:10.1038/s41586-020-2649-2", "https://doi.org/10.1038/s41586-020-2649-2"),
        # Scheme-less links: doi.org itself, and the placeholder's own arXiv example.
        ("doi.org/10.1038/s41586-020-2649-2", "https://doi.org/10.1038/s41586-020-2649-2"),
        ("arxiv.org/abs/2401.01234", "https://arxiv.org/abs/2401.01234"),
        ("pubmed.ncbi.nlm.nih.gov/38278431", "https://pubmed.ncbi.nlm.nih.gov/38278431"),
    ],
)
def test_resolve_accepts_bare_dois_and_schemeless_links(signed_in, pasted, coerced):
    resp = client.post("/resolve", json={"url": pasted, "network": False}, headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == coerced
    # The identifier is recognised on the coerced URL, so the right resolver runs.
    assert data["source"] != "unknown"


def test_resolve_coercion_does_not_bypass_the_ssrf_guard(signed_in):
    """Prepending https:// must not smuggle an internal host past the guard."""
    resp = client.post("/resolve", json={"url": "localhost/admin", "network": False}, headers=AUTH)
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "pasted",
    [
        "2130706433/",  # decimal 127.0.0.1
        "0x7f000001/",  # hex 127.0.0.1
        "127.1/",  # short-form loopback
        "127.000.000.001/",  # zero-padded octets
    ],
)
def test_resolve_does_not_coerce_encoded_internal_ips(signed_in, pasted):
    """These have no scheme, so pre-coercion they hard-400'd at the syntactic gate.
    Coercion must not rescue them into hosts the fast gate can't recognise as IPs —
    they don't look like hostnames, so they stay rejected with a clean 400 rather
    than reaching the fetch layer as the sole line of defence."""
    resp = client.post("/resolve", json={"url": pasted, "network": False}, headers=AUTH)
    assert resp.status_code == 400


def test_posts_with_fields_coerces_bare_doi(monkeypatch):
    """A bare DOI posted with fields (e.g. from a non-web client) must be stored as its
    doi.org URL, so it dedupes against the same paper added via /resolve — the fields
    path used to store the raw '10.x/y' string verbatim."""
    import api.app as app_mod

    seen: dict = {}
    monkeypatch.setattr(app_mod, "_require_member", lambda _t, _team: "user-1")
    monkeypatch.setattr(
        app_mod,
        "_upsert_paper",
        lambda meta, url, url_norm: (seen.update(url=url, url_norm=url_norm), ("paper-1", False))[1],
    )
    monkeypatch.setattr(app_mod, "_create_post", lambda *_a, **_k: ("post-1", False, "web"))

    resp = client.post(
        "/posts",
        json={
            "url": "10.1016/j.cell.2011.02.013",
            "team_id": "t",
            "fields": {"title": "Hallmarks of Cancer", "source": "manual"},
        },
        headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    assert seen["url"] == "https://doi.org/10.1016/j.cell.2011.02.013"
    assert seen["url_norm"] == "//doi.org/10.1016/j.cell.2011.02.013"


def test_posts_requires_bearer_token():
    # No Authorization header → 401 before any Supabase call.
    resp = client.post("/posts", json={"url": "https://arxiv.org/abs/2401.01234", "team_id": "x"})
    assert resp.status_code == 401


def test_semantic_search_requires_bearer_token():
    resp = client.post("/search/semantic", json={"query": "x", "team_id": "t"})
    assert resp.status_code == 401


def test_overview_requires_bearer_token():
    resp = client.get("/overview", params={"team_id": "t"})
    assert resp.status_code == 401


def test_similarity_requires_bearer_token():
    resp = client.post("/similarity", json={"query": "x", "team_id": "t"})
    assert resp.status_code == 401


def test_profile_requires_bearer_token():
    resp = client.post("/profile", json={"profile_md": "I study spatial biology"})
    assert resp.status_code == 401


def test_recommendations_requires_bearer_token():
    resp = client.get("/recommendations", params={"team_id": "t"})
    assert resp.status_code == 401


def test_l2norm_returns_unit_vector():
    import numpy as np

    from api.app import _l2norm

    out = _l2norm(np.array([3.0, 4.0], dtype=np.float32))
    assert abs(float(np.linalg.norm(out)) - 1.0) < 1e-6
    # a zero vector is returned unchanged (no divide-by-zero)
    zero = _l2norm(np.zeros(4, dtype=np.float32))
    assert float(np.linalg.norm(zero)) == 0.0


def test_parse_vec_handles_string_and_list():
    from api.app import _parse_vec

    assert _parse_vec("[0.1, 0.2, 0.3]") == [0.1, 0.2, 0.3]
    assert _parse_vec([0.1, 0.2]) == [0.1, 0.2]
    assert _parse_vec(None) is None


def test_recency_decay_halves_at_halflife():
    from datetime import UTC, datetime, timedelta

    from api.app import _HALFLIFE_DAYS, _recency_decay

    now = datetime(2026, 7, 1, tzinfo=UTC)
    assert _recency_decay(now, now) == 1.0  # brand new
    half = now - timedelta(days=_HALFLIFE_DAYS)
    assert abs(_recency_decay(half, now) - 0.5) < 1e-6  # one half-life → 0.5
    assert _recency_decay(None, now) == 1.0  # missing timestamp → no decay
    # a future timestamp doesn't amplify weight
    assert _recency_decay(now + timedelta(days=5), now) == 1.0


def test_parse_ts_handles_iso_and_z():
    from api.app import _parse_ts

    assert _parse_ts("2026-07-01T12:00:00+00:00") is not None
    assert _parse_ts("2026-07-01T12:00:00Z") is not None  # Z offset
    assert _parse_ts(None) is None
    assert _parse_ts("not-a-date") is None


def test_compute_stats_aggregates_posts():
    from api.app import _compute_stats

    rows = [
        {
            "posted_at": "2026-03-09T12:00:00Z",
            "papers": {"venue": "Nature", "year": 2025, "authors": ["A. One", "B. Last"]},
        },
        {
            "posted_at": "2026-03-20T12:00:00Z",
            "papers": {"venue": "Nature", "year": 2026, "authors": ["C. Only"]},
        },
        {
            "posted_at": "2026-04-01T12:00:00Z",
            "papers": {"venue": "bioRxiv", "year": 2026, "authors": []},
        },
    ]
    stats = _compute_stats(rows)
    assert stats.over_time == [{"month": "2026-03", "count": 2}, {"month": "2026-04", "count": 1}]
    assert stats.by_venue[0] == {"venue": "Nature", "count": 2}
    assert {"year": 2026, "count": 2} in stats.by_year
    # last author is the lab proxy; the empty-author row contributes nothing
    labs = {d["lab"]: d["count"] for d in stats.by_lab}
    assert labs == {"B. Last": 1, "C. Only": 1}


def test_resolve_dedup_key_strips_tracking_params(signed_in):
    resp = client.post(
        "/resolve",
        json={
            "url": "https://www.nature.com/articles/s41586-024-01234-5?utm_source=x&fbclid=y",
            "network": False,
        },
        headers=AUTH,
    )
    assert resp.status_code == 200
    norm = resp.json()["url_norm"]
    assert norm == "//nature.com/articles/s41586-024-01234-5"


# --- SSRF guard on the URL-fetching endpoints ------------------------------


SSRF_URLS = [
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata — the classic target
    "http://127.0.0.1:8000/admin",
    "http://localhost/x",
    "https://10.0.0.5/a",
    "http://192.168.1.1/a",
    "http://[::1]/a",
    "http://100.100.100.200/latest/meta-data/",  # CGNAT metadata — was a bypass
    "http://239.255.255.250/",  # multicast — was a bypass
    "http://169.254.169.254./",  # trailing dot — was a bypass
    "https://svc.internal/x",
    "file:///etc/passwd",
    "ftp://host/x",
    "http://[::1",  # malformed — must be a clean 400, not a 500
]


@pytest.mark.parametrize("url", SSRF_URLS)
def test_resolve_refuses_to_fetch_internal_addresses(signed_in, monkeypatch, url):
    """A member can still reach /resolve, so auth alone doesn't make the fetch safe."""
    import api.app as app_mod

    def _no_fetch(*_a, **_k):
        raise AssertionError(f"the server must not fetch {url}")

    monkeypatch.setattr(app_mod, "fetch_metadata", _no_fetch)

    resp = client.post("/resolve", json={"url": url}, headers=AUTH)
    assert resp.status_code == 400, f"{url} was accepted"


@pytest.mark.parametrize("url", SSRF_URLS)
def test_posts_refuses_to_fetch_internal_addresses(monkeypatch, url):
    """/posts resolves the URL server-side when the client sends no `fields` — the
    same sink as /resolve, reachable by any lab member."""
    import api.app as app_mod

    def _no_fetch(*_a, **_k):
        raise AssertionError(f"the server must not fetch {url}")

    monkeypatch.setattr(app_mod, "_require_member", lambda _t, _team: "user-1")
    monkeypatch.setattr(app_mod, "fetch_metadata", _no_fetch)
    monkeypatch.setattr(app_mod, "_upsert_paper", _no_fetch)

    resp = client.post("/posts", json={"url": url, "team_id": "t"}, headers=AUTH)
    assert resp.status_code == 400, f"{url} was accepted"


def test_resolve_is_rate_limited(signed_in, monkeypatch):
    """Each call costs an outbound request, so it's an amplifier if left unbounded."""
    import api.app as app_mod

    monkeypatch.setattr(
        app_mod, "_resolve_limiter", app_mod._PerUserRateLimiter(max_events=3, window_seconds=60.0)
    )
    body = {"url": "https://arxiv.org/abs/2401.01234", "network": False}
    for _ in range(3):
        assert client.post("/resolve", json=body, headers=AUTH).status_code == 200
    assert client.post("/resolve", json=body, headers=AUTH).status_code == 429


def test_blocked_url_does_not_spend_rate_limit_quota(signed_in, monkeypatch):
    """A rejected URL never fetches, so it must not burn one of the caller's 30/min."""
    import api.app as app_mod

    monkeypatch.setattr(
        app_mod, "_resolve_limiter", app_mod._PerUserRateLimiter(max_events=1, window_seconds=60.0)
    )
    # A blocked URL 400s and spends nothing...
    assert (
        client.post("/resolve", json={"url": "http://127.0.0.1/x"}, headers=AUTH).status_code == 400
    )
    # ...so the one real call still has its quota.
    body = {"url": "https://arxiv.org/abs/2401.01234", "network": False}
    assert client.post("/resolve", json=body, headers=AUTH).status_code == 200


def test_posts_with_fields_does_not_validate_or_fetch_url(monkeypatch):
    """The reviewed-fields path never fetches, so it must not run the SSRF/URL check —
    a hand-entered link the resolver can't reach (a bare DOI, a bot-walled page) must
    still post, and the network-free path must stay network-free."""
    import api.app as app_mod

    seen: dict = {}
    monkeypatch.setattr(app_mod, "_require_member", lambda _t, _team: "user-1")
    monkeypatch.setattr(
        app_mod,
        "_upsert_paper",
        lambda meta, _u, _n: (seen.update(meta=meta), ("paper-1", False))[1],
    )
    monkeypatch.setattr(app_mod, "_create_post", lambda *_a, **_k: ("post-1", False, "web"))

    def _no_fetch(*_a, **_k):
        raise AssertionError("the fields path must not fetch or validate for a fetch")

    monkeypatch.setattr(app_mod, "fetch_metadata", _no_fetch)
    monkeypatch.setattr(app_mod, "_validated_fetch_url", _no_fetch)

    # A bare DOI as the "link" — not a fetchable http URL, but with fields it must post.
    resp = client.post(
        "/posts",
        json={
            "url": "10.1016/j.cell.2011.02.013",
            "team_id": "t",
            "fields": {"title": "Hallmarks of Cancer", "source": "manual"},
        },
        headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    assert seen["meta"].title == "Hallmarks of Cancer"


def test_rate_limiter_is_thread_safe():
    """Concurrent callers must not both slip past the cap, and the >10k eviction must
    not crash mid-rebuild. Exercises the lock directly, off the HTTP path."""
    import threading

    from api.app import _PerUserRateLimiter

    rl = _PerUserRateLimiter(max_events=100, window_seconds=60.0)
    admitted = 0
    admitted_lock = threading.Lock()

    def hammer():
        nonlocal admitted
        for _ in range(50):
            try:
                rl.check("same-user")
                with admitted_lock:
                    admitted += 1
            except Exception:
                pass

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 8×50 = 400 attempts, cap 100: an unsynchronized limiter would admit >100 (or crash).
    assert admitted == 100


# --- BibTeX import ---------------------------------------------------------


def test_bibtex_endpoints_require_a_bearer_token():
    for path in ("/import/bibtex/preflight", "/import/bibtex"):
        resp = client.post(path, json={"team_id": "x", "bibtex": "@article{a}"})
        assert resp.status_code in (401, 403), path


def test_bibtex_preflight_refuses_a_lab_you_are_not_in(monkeypatch):
    """The pre-flight reads with the service role (it must, to see papers other members
    posted), so RLS can't protect it. Without an explicit membership check, `team_id` is
    attacker-controlled and a "duplicate" verdict tells you a lab you can't see holds
    that DOI — an oracle over any lab's corpus."""
    import api.app as app_mod

    monkeypatch.setattr(app_mod, "get_user_id", lambda _t: "attacker")

    class _NoMembership:
        def table(self, _n):
            return self

        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def limit(self, *_a):
            return self

        def execute(self):
            return type("R", (), {"data": []})()  # not a member of anything

    monkeypatch.setattr(app_mod, "user_client", lambda _t: _NoMembership())

    for path in ("/import/bibtex/preflight", "/import/bibtex"):
        resp = client.post(
            path,
            json={"team_id": "someone-elses-lab", "bibtex": "@article{a, doi={10.1/x}}"},
            headers={"Authorization": "Bearer forged"},
        )
        assert resp.status_code == 403, f"{path} leaked: {resp.status_code}"
        assert "not a member" in resp.json()["detail"].lower()


def test_bibtex_payload_is_bounded():
    """An unbounded `bibtex` string lets one request exhaust the process."""
    resp = client.post(
        "/import/bibtex/preflight",
        json={"team_id": "x", "bibtex": "a" * (app_mod_max() + 1)},
        headers={"Authorization": "Bearer whatever"},
    )
    assert resp.status_code == 422


def app_mod_max() -> int:
    from api.app import MAX_BIBTEX_BYTES

    return MAX_BIBTEX_BYTES


# --- posting reviewed / hand-typed metadata --------------------------------


def _stub_post(monkeypatch, seen: dict):
    """Wire /posts up to nothing: capture the metadata it would store, write nothing."""
    import api.app as app_mod

    monkeypatch.setattr(app_mod, "_require_member", lambda _t, _team: "user-1")
    monkeypatch.setattr(
        app_mod,
        "_upsert_paper",
        lambda meta, _url, _norm: (seen.update(meta=meta), ("paper-1", False))[1],
    )
    monkeypatch.setattr(app_mod, "_create_post", lambda *_a, **_k: ("post-1", False, "web"))

    def _boom(*_a, **_k):
        raise AssertionError("fetch_metadata must not run when the client sent fields")

    monkeypatch.setattr(app_mod, "fetch_metadata", _boom)


def test_posting_reviewed_fields_stores_them_without_refetching(monkeypatch):
    """The whole point of the Add-paper dialog: a bot-walled publisher resolves to an
    empty record, so the user types the title in. If the server re-fetched the URL it
    would overwrite that title with the same nothing it got the first time."""
    seen: dict = {}
    _stub_post(monkeypatch, seen)  # fetch_metadata now raises if called

    resp = client.post(
        "/posts",
        json={
            "url": "https://www.cell.com/cell/fulltext/S0092-8674(23)00001-0",
            "team_id": "team-1",
            "fields": {
                "title": "Hallmarks of cancer: the next generation",
                "authors": ["Douglas Hanahan", "Robert A. Weinberg"],
                "venue": "Cell",
                "year": 2023,
                "source": "manual",
            },
        },
        headers={"Authorization": "Bearer good"},
    )

    assert resp.status_code == 200, resp.text
    meta = seen["meta"]
    assert meta.title == "Hallmarks of cancer: the next generation"
    assert meta.authors == ["Douglas Hanahan", "Robert A. Weinberg"]
    assert meta.venue == "Cell"
    assert meta.year == 2023
    # Don't credit a resolver for what a human typed.
    assert meta.source == "manual"


def test_posting_without_fields_still_resolves_server_side(monkeypatch):
    """The CLI and older clients send a bare URL and rely on the server to resolve it."""
    import api.app as app_mod
    from paper_radar.ingest.metadata import PaperMetadata

    seen: dict = {}
    monkeypatch.setattr(app_mod, "_require_member", lambda _t, _team: "user-1")
    monkeypatch.setattr(
        app_mod,
        "_upsert_paper",
        lambda meta, _url, _norm: (seen.update(meta=meta), ("paper-1", False))[1],
    )
    monkeypatch.setattr(app_mod, "_create_post", lambda *_a, **_k: ("post-1", False, "web"))
    monkeypatch.setattr(
        app_mod,
        "fetch_metadata",
        lambda url: PaperMetadata(url=url, title="Resolved by the server", source="arxiv"),
    )

    resp = client.post(
        "/posts",
        json={"url": "https://arxiv.org/abs/2401.01234", "team_id": "team-1"},
        headers={"Authorization": "Bearer good"},
    )

    assert resp.status_code == 200, resp.text
    assert seen["meta"].title == "Resolved by the server"


def test_posting_to_a_lab_you_are_not_in_writes_nothing(monkeypatch):
    """`_upsert_paper` runs with the service role and can now *repair* an existing
    `papers` row, not just insert one. If membership were left to RLS on the paper_post
    insert (which happens after), a non-member's hand-typed metadata would already be
    on a row every other lab sharing that paper can see by the time the 403 lands."""
    import api.app as app_mod

    def _no_writes(*_a, **_k):
        raise AssertionError("nothing may be written before membership is checked")

    monkeypatch.setattr(app_mod, "get_user_id", lambda _t: "attacker")
    monkeypatch.setattr(app_mod, "_upsert_paper", _no_writes)
    monkeypatch.setattr(app_mod, "_create_post", _no_writes)
    monkeypatch.setattr(app_mod, "fetch_metadata", _no_writes)

    class _NoMembership:
        def table(self, _n):
            return self

        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def limit(self, *_a):
            return self

        def execute(self):
            return type("R", (), {"data": []})()  # not a member of anything

    monkeypatch.setattr(app_mod, "user_client", lambda _t: _NoMembership())

    resp = client.post(
        "/posts",
        json={
            "url": "https://arxiv.org/abs/2401.01234",
            "team_id": "someone-elses-lab",
            "fields": {"title": "spam", "source": "manual"},
        },
        headers={"Authorization": "Bearer forged"},
    )
    assert resp.status_code == 403
    assert "not a member" in resp.json()["detail"].lower()


@pytest.mark.parametrize(
    "fields",
    [
        {"title": "x" * 2_001},
        {"abstract": "x" * 100_001},
        {"authors": ["a" * 301]},  # one oversized item, not just too many
        {"authors": ["a"] * 1_001},
        {"year": 99_999_999_999},  # papers.year is int4 — would 500 on insert
        {"source": "crossref-but-i-typed-it"},  # provenance is an enum, not free text
    ],
)
def test_paper_fields_are_bounded(monkeypatch, fields):
    """These land in `papers` verbatim, so an unbounded field is an unbounded write —
    the same hazard MAX_BIBTEX_BYTES already guards on the import path."""
    import api.app as app_mod

    def _no_writes(*_a, **_k):
        raise AssertionError("a rejected payload must not reach the database")

    monkeypatch.setattr(app_mod, "_require_member", lambda _t, _team: "user-1")
    monkeypatch.setattr(app_mod, "_upsert_paper", _no_writes)

    resp = client.post(
        "/posts",
        json={"url": "https://arxiv.org/abs/2401.01234", "team_id": "t", "fields": fields},
        headers={"Authorization": "Bearer good"},
    )
    assert resp.status_code == 422, f"{fields} was accepted"


def test_repair_untitled_fills_a_blank_but_never_overwrites(monkeypatch):
    """The manual path is useless if a URL someone already posted (titleless, because it
    was bot-walled) can't adopt the title now typed for it — but a row that already has
    a title must not be rewritten by whatever the next person types."""
    import api.app as app_mod
    from paper_radar.ingest.metadata import PaperMetadata

    patches: list[dict] = []

    class _Svc:
        def table(self, _n):
            return self

        def update(self, patch):
            patches.append(patch)
            return self

        def eq(self, *_a):
            return self

        def execute(self):
            return type("R", (), {"data": []})()

    monkeypatch.setattr(app_mod, "service_client", lambda: _Svc())

    typed = PaperMetadata(url="u", title="Typed by hand", authors=["A"], source="manual")

    # A titleless row adopts it, and is marked for embedding (it now has text).
    assert app_mod._repair_untitled({"id": "p1", "title": None}, typed) is True
    assert patches[0]["title"] == "Typed by hand"
    assert patches[0]["embedded_at"] is None

    # A row that already has a title is left alone.
    assert app_mod._repair_untitled({"id": "p2", "title": "Real title"}, typed) is False
    assert len(patches) == 1


def test_norm_doi_casefolds_and_strips_resolver_prefix():
    """DOIs are case-insensitive (ISO 26324) — the dedup key must fold case.

    Regression: AACR registers "...CD-25-1745" and PubMed reports "...cd-25-1745",
    so the same paper posted from both sources landed as two rows.
    """
    from api.app import _norm_doi

    upper = "10.1158/2159-8290.CD-25-1745"
    lower = "10.1158/2159-8290.cd-25-1745"
    assert _norm_doi(upper) == _norm_doi(lower) == lower

    # the resolver prefix is not part of the DOI
    assert _norm_doi("https://doi.org/10.1038/S41586-024-1") == "10.1038/s41586-024-1"
    assert _norm_doi("doi:10.1038/s41586-024-1") == "10.1038/s41586-024-1"

    # empty-ish input stays None rather than becoming a key that matches everything
    assert _norm_doi(None) is None
    assert _norm_doi("") is None
    assert _norm_doi("   ") is None
