"""Clinical trials, PR 1: the registry client, paper↔trial linking, the API gate."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_radar.trials import ctgov

FIXTURES = Path(__file__).parent / "fixtures" / "ctgov"


def _fixture(nct: str) -> dict:
    return json.loads((FIXTURES / f"{nct}.json").read_text())


# --- the registry record ------------------------------------------------------


@pytest.mark.parametrize(
    ("nct", "acronym", "phases", "enrollment"),
    [
        # No acronym field: the name sits in the title's brackets.
        ("NCT03036488", "KEYNOTE-522", ["PHASE3"], 1174),
        ("NCT02620280", "NeoTRIPaPDL1", ["PHASE3"], 278),
        # No acronym field and none in the title: a secondary ID.
        ("NCT03197935", "IMpassion031", ["PHASE3"], 333),
        ("NCT02685059", "GeparNuevo", ["PHASE2"], 174),
    ],
)
def test_parse_registry_records(nct, acronym, phases, enrollment):
    rec = ctgov.parse(_fixture(nct))
    assert rec.nct_id == nct
    assert rec.acronym == acronym
    assert rec.phases == phases
    assert rec.enrollment == enrollment
    assert rec.status == "COMPLETED"
    assert rec.is_breast_cancer
    assert rec.registry["identificationModule"]["nctId"] == nct
    assert len(rec.registry_updated_at) == 10


def test_parse_rejects_a_record_without_an_nct_id():
    with pytest.raises(ctgov.RegistryError):
        ctgov.parse({"protocolSection": {"identificationModule": {}}})
    with pytest.raises(ctgov.RegistryError):
        ctgov.parse({})


def test_partial_last_update_date_is_dropped():
    data = _fixture("NCT02685059")
    data["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"]["date"] = "2021-02"
    assert ctgov.parse(data).registry_updated_at is None


def test_not_breast_cancer():
    rec = ctgov.TrialRecord(nct_id="NCT00000001", title="Lung study", conditions=["NSCLC"])
    assert not rec.is_breast_cancer


@pytest.mark.parametrize(
    ("ident", "expected"),
    [
        ({"acronym": " monarchE "}, "monarchE"),
        ({"briefTitle": "Pembrolizumab in TNBC (MK-3475-522/KEYNOTE-522)"}, "KEYNOTE-522"),
        # Brackets with an abbreviation, not a name; then a secondary ID.
        (
            {
                "briefTitle": "A study in breast cancer (TNBC)",
                "secondaryIdInfos": [
                    {"id": "2016-004740-11", "type": "EUDRACT_NUMBER"},
                    {"id": "WO29522", "type": None},
                    {"id": "IMpassion031", "type": "OTHER"},
                ],
            },
            "IMpassion031",
        ),
        ({"briefTitle": "No name here"}, None),
    ],
)
def test_pick_acronym(ident, expected):
    assert ctgov.pick_acronym(ident) == expected


def test_find_and_normalise_nct_ids():
    text = "Registered as NCT03036488 (nct 03036488) and NCT02620280; not NCT123."
    assert ctgov.find_nct_ids(text) == ["NCT03036488", "NCT02620280"]
    assert ctgov.find_nct_ids(None) == []
    assert ctgov.normalise_nct(" nct03036488 ") == "NCT03036488"
    assert ctgov.normalise_nct("NCT0303648") is None
    assert ctgov.normalise_nct("KEYNOTE-522") is None


# --- talking to the registry -----------------------------------------------------


def _respond(monkeypatch, handler):
    def fake_urlopen(req, timeout):
        return handler(req.full_url)

    monkeypatch.setattr(ctgov.urllib.request, "urlopen", fake_urlopen)


class _Body(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_404_is_none_and_other_errors_raise(monkeypatch):
    def not_found(url):
        raise urllib.error.HTTPError(url, 404, "nf", None, None)

    _respond(monkeypatch, not_found)
    assert ctgov.fetch("NCT00000000") is None

    def down(url):
        raise urllib.error.HTTPError(url, 503, "down", None, None)

    _respond(monkeypatch, down)
    with pytest.raises(ctgov.RegistryError):
        ctgov.fetch("NCT00000000")

    with pytest.raises(ValueError):
        ctgov.fetch("KEYNOTE-522")


def test_fetch_parses(monkeypatch):
    _respond(monkeypatch, lambda url: _Body(json.dumps(_fixture("NCT03036488")).encode()))
    assert ctgov.fetch("NCT03036488").acronym == "KEYNOTE-522"


def test_search_tries_ids_first_then_free_text(monkeypatch):
    seen = []

    def handler(url):
        seen.append(url)
        if "query.id=" in url:
            studies = [_fixture("NCT03036488")]
        else:  # free text: one repeat, one new
            studies = [_fixture("NCT03036488"), _fixture("NCT02620280")]
        return _Body(json.dumps({"studies": studies}).encode())

    _respond(monkeypatch, handler)
    hits = ctgov.search("KEYNOTE-522", limit=5)
    assert [h.nct_id for h in hits] == ["NCT03036488", "NCT02620280"]
    assert hits[0].acronym == "KEYNOTE-522"
    assert "query.id=KEYNOTE-522" in seen[0] and "query.cond=breast" in seen[0]
    assert "query.term=" in seen[1]


def test_search_by_nct_fetches_that_trial(monkeypatch):
    _respond(monkeypatch, lambda url: _Body(json.dumps(_fixture("NCT02685059")).encode()))
    hits = ctgov.search("nct02685059")
    assert [(h.nct_id, h.acronym) for h in hits] == [("NCT02685059", "GeparNuevo")]


# --- linking papers to trials ------------------------------------------------------

trial_links = pytest.importorskip("api.trial_links")
# conftest turns link_paper into a no-op for every test; keep the real one.
_real_link_paper = trial_links.link_paper


def test_acronym_pattern():
    kn = trial_links.acronym_pattern("KEYNOTE-522")
    assert kn.search("Pembrolizumab in keynote-522: 5-year results")
    assert not kn.search("KEYNOTE-5220 results")
    assert not kn.search("MK-KEYNOTE-522x")
    # All letters: case matters, so an ordinary word isn't a trial.
    ascent = trial_links.acronym_pattern("ASCENT")
    assert ascent.search("Sacituzumab in ASCENT")
    assert not ascent.search("The ascent of ADCs")
    assert trial_links.acronym_pattern("ACE") is None
    assert trial_links.acronym_pattern(None) is None


class _FakeSvc:
    """Records upserts; answers reads from canned rows per table."""

    def __init__(self, reads=None):
        self.reads = reads or {}
        self.upserts: list[tuple[str, object]] = []

    def table(self, name):
        svc = self

        class Q:
            def __getattr__(self, _attr):
                return lambda *a, **k: self

            def upsert(self, rows, **_k):
                svc.upserts.append((name, rows))
                return self

            def execute(self):
                return SimpleNamespace(data=svc.reads.get(name, []))

        return Q()


def test_link_papers(monkeypatch):
    svc = _FakeSvc()
    monkeypatch.setattr(trial_links, "service_client", lambda: svc)
    monkeypatch.setattr(
        trial_links,
        "_lab_trials",
        lambda _s, _t: {
            "NCT03036488": {"id": "t-kn", "nct_id": "NCT03036488", "acronym": "KEYNOTE-522"}
        },
    )
    # The lab already rejected p3's suggestion.
    monkeypatch.setattr(trial_links, "_decided", lambda _s, _t, _ids: {("p3", "t-kn")})
    fetched = []

    def ensure(_s, nct, cache=None):
        fetched.append(nct)
        return {"NCT02620280": "t-neo", "NCT09999999": None}[nct]

    monkeypatch.setattr(trial_links, "ensure_trial", ensure)

    n = trial_links.link_papers(
        "lab",
        [
            {
                "id": "p1",
                "title": "Primary results",
                "abstract": "ClinicalTrials.gov: NCT03036488.",
            },
            {
                "id": "p2",
                "title": "KEYNOTE-522 overall survival",
                "abstract": "Also NCT02620280 and NCT09999999.",
            },
            {"id": "p3", "title": "KEYNOTE-522 again", "abstract": None},
        ],
    )

    assert fetched == ["NCT02620280", "NCT09999999"]  # the lab's own trial isn't fetched
    posts = [rows for name, rows in svc.upserts if name == "trial_posts"]
    assert posts == [{"trial_id": "t-neo", "team_id": "lab", "source": "paper"}]
    (links,) = [rows for name, rows in svc.upserts if name == "paper_trials"]
    got = {(r["paper_id"], r["trial_id"]): (r["source"], r["status"]) for r in links}
    assert got == {
        ("p1", "t-kn"): ("nct_in_abstract", "auto"),
        ("p2", "t-neo"): ("nct_in_abstract", "auto"),
        ("p2", "t-kn"): ("acronym_in_title", "suggested"),
    }
    assert n == 3


def test_ensure_trial_skips_non_breast_and_caches(monkeypatch):
    svc = _FakeSvc()
    calls = []

    def fetch(nct):
        calls.append(nct)
        return ctgov.TrialRecord(nct_id=nct, title="Lung", conditions=["NSCLC"])

    monkeypatch.setattr(ctgov, "fetch", fetch)
    cache: dict = {}
    assert trial_links.ensure_trial(svc, "NCT00000001", cache=cache) is None
    assert trial_links.ensure_trial(svc, "NCT00000001", cache=cache) is None
    assert calls == ["NCT00000001"]
    assert not svc.upserts


def test_ensure_trial_does_not_cache_registry_failures(monkeypatch):
    def down(_nct):
        raise ctgov.RegistryError("down")

    monkeypatch.setattr(ctgov, "fetch", down)
    cache: dict = {}
    assert trial_links.ensure_trial(_FakeSvc(), "NCT00000001", cache=cache) is None
    assert cache == {}


def test_link_paper_does_nothing_for_labs_without_the_feature(monkeypatch):
    monkeypatch.setattr(trial_links, "active_teams", lambda: {"other-lab"})
    monkeypatch.setattr(trial_links, "service_client", lambda: pytest.fail("must not read"))
    monkeypatch.setattr(trial_links, "link_papers", lambda *_a, **_k: pytest.fail("must not link"))
    _real_link_paper("lab", "p1")


def test_link_paper_links_for_labs_with_the_feature(monkeypatch):
    monkeypatch.setattr(trial_links, "active_teams", lambda: {"lab"})
    monkeypatch.setattr(trial_links, "service_client", lambda: _FakeSvc({"papers": [{"id": "p1"}]}))
    got = []
    monkeypatch.setattr(trial_links, "link_papers", lambda team, papers: got.append((team, papers)))
    _real_link_paper("lab", "p1")
    assert got == [("lab", [{"id": "p1"}])]


# --- the API ---------------------------------------------------------------------

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import api.trials as trials_api  # noqa: E402
from api.app import app  # noqa: E402

client = TestClient(app)
AUTH = {"Authorization": "Bearer t"}


class _Rpc:
    def __init__(self, answer):
        self.answer = answer

    def rpc(self, *_a, **_k):
        return self

    def execute(self):
        return SimpleNamespace(data=self.answer)


def test_endpoints_404_without_the_feature(monkeypatch):
    monkeypatch.setattr(trials_api, "get_user_id", lambda _t: "u1")
    monkeypatch.setattr(trials_api, "user_client", lambda _t: _Rpc(False))
    monkeypatch.setattr(ctgov, "search", lambda *_a, **_k: pytest.fail("must not search"))

    r = client.get("/trials/search", params={"team_id": "lab", "q": "KEYNOTE"}, headers=AUTH)
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}
    r = client.post("/trials", json={"team_id": "lab", "nct_id": "NCT03036488"}, headers=AUTH)
    assert r.status_code == 404


def test_add_rejects_bad_ids_and_non_breast_trials(monkeypatch):
    monkeypatch.setattr(trials_api, "_require_feature", lambda _t, _team: "u1")
    monkeypatch.setattr(trials_api, "_limit", lambda _u: None)
    monkeypatch.setattr(trials_api, "service_client", lambda: _FakeSvc())

    r = client.post("/trials", json={"team_id": "lab", "nct_id": "KEYNOTE-5222"}, headers=AUTH)
    assert r.status_code == 400

    monkeypatch.setattr(ctgov, "fetch", lambda nct: None)
    r = client.post("/trials", json={"team_id": "lab", "nct_id": "NCT00000001"}, headers=AUTH)
    assert r.status_code == 404
    assert "isn't on ClinicalTrials.gov" in r.json()["detail"]

    monkeypatch.setattr(
        ctgov,
        "fetch",
        lambda nct: ctgov.TrialRecord(nct_id=nct, title="Lung", conditions=["NSCLC"]),
    )
    r = client.post("/trials", json={"team_id": "lab", "nct_id": "NCT00000001"}, headers=AUTH)
    assert r.status_code == 422
