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


def test_search_by_nct_leaves_out_other_cancers(monkeypatch):
    lung = _fixture("NCT02685059")
    lung["protocolSection"]["conditionsModule"] = {"conditions": ["NSCLC"]}
    ident = lung["protocolSection"]["identificationModule"]
    ident["briefTitle"] = ident["officialTitle"] = "A lung study"
    _respond(monkeypatch, lambda url: _Body(json.dumps(lung).encode()))
    assert ctgov.search("NCT02685059") == []
    assert [h.nct_id for h in ctgov.search("NCT02685059", condition=None)] == ["NCT02685059"]


def test_search_by_nct_fetches_that_trial(monkeypatch):
    _respond(monkeypatch, lambda url: _Body(json.dumps(_fixture("NCT02685059")).encode()))
    hits = ctgov.search("nct02685059")
    assert [(h.nct_id, h.acronym) for h in hits] == [("NCT02685059", "GeparNuevo")]


# --- linking papers to trials ------------------------------------------------------

from api import trial_links  # noqa: E402

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
    """Records upserts; answers reads from canned rows per table. An upsert of
    one row answers with that row and an id."""

    def __init__(self, reads=None):
        self.reads = reads or {}
        self.upserts: list[tuple[str, object]] = []

    def table(self, name):
        svc = self

        class Q:
            upserted = None

            def __getattr__(self, _attr):
                return lambda *a, **k: self

            def upsert(self, rows, **_k):
                svc.upserts.append((name, rows))
                self.upserted = rows
                return self

            def execute(self):
                if isinstance(self.upserted, dict):
                    return SimpleNamespace(data=[{"id": f"{name}-id", **self.upserted}])
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
    # The lab already rejected p3's suggestion, and took t-gone off its list.
    monkeypatch.setattr(trial_links, "_decided", lambda _s, _t, _ids: {("p3", "t-kn"): "rejected"})
    monkeypatch.setattr(trial_links, "_removed", lambda _s, _t: {"t-gone"})
    fetched = []

    def ensure(_s, nct, _lookup):
        fetched.append(nct)
        return {"NCT02620280": "t-neo", "NCT09999999": None, "NCT01111111": "t-gone"}[nct]

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
                "abstract": "Also NCT02620280, NCT09999999 and NCT01111111.",
            },
            {"id": "p3", "title": "KEYNOTE-522 again", "abstract": None},
        ],
    )

    # The lab's own trial isn't fetched; the removed one is neither re-added nor linked.
    assert fetched == ["NCT02620280", "NCT09999999", "NCT01111111"]
    posts = [rows for name, rows in svc.upserts if name == "trial_posts"]
    assert posts == [{"trial_id": "t-neo", "team_id": "lab", "source": "paper"}]
    (links,) = [rows for name, rows in svc.upserts if name == "paper_trials"]
    got = {(r["paper_id"], r["trial_id"]): (r["source"], r["status"]) for r in links}
    assert got == {
        ("p1", "t-kn"): ("nct_in_abstract", "auto"),
        ("p2", "t-neo"): ("nct_in_abstract", "auto"),
        ("p2", "t-kn"): ("acronym_in_title", "suggested"),
    }
    assert n.count == 3
    assert n.trials == {"t-kn", "t-neo"}  # the suggestion isn't a reason to fetch


def test_ensure_trial_stores_non_breast_trials_once(monkeypatch):
    svc = _FakeSvc()
    calls = []

    def fetch(nct):
        calls.append(nct)
        return ctgov.TrialRecord(nct_id=nct, title="Lung", conditions=["NSCLC"])

    monkeypatch.setattr(ctgov, "fetch", fetch)
    lookup = trial_links.Lookup()
    assert trial_links.ensure_trial(svc, "NCT00000001", lookup) is None
    assert trial_links.ensure_trial(svc, "NCT00000001", lookup) is None
    assert calls == ["NCT00000001"]
    # Stored, flagged, so tomorrow's run reads it instead of fetching it.
    [(table, row)] = svc.upserts
    assert table == "trials" and row["breast_cancer"] is False


def test_ensure_trial_reads_the_stored_flag(monkeypatch):
    monkeypatch.setattr(ctgov, "fetch", lambda _n: pytest.fail("must not fetch"))
    lookup = trial_links.Lookup()
    stored = _FakeSvc({"trials": [{"id": "t1", "breast_cancer": True}]})
    assert trial_links.ensure_trial(stored, "NCT00000001", lookup) == "t1"
    other = _FakeSvc({"trials": [{"id": "t2", "breast_cancer": False}]})
    assert trial_links.ensure_trial(other, "NCT00000002", lookup) is None


def test_ensure_trial_stops_asking_once_the_registry_fails(monkeypatch):
    calls = []

    def down(nct):
        calls.append(nct)
        raise ctgov.RegistryError("down")

    monkeypatch.setattr(ctgov, "fetch", down)
    lookup = trial_links.Lookup()
    assert trial_links.ensure_trial(_FakeSvc(), "NCT00000001", lookup) is None
    assert trial_links.ensure_trial(_FakeSvc(), "NCT00000002", lookup) is None
    assert calls == ["NCT00000001"]
    assert lookup.answers == {}  # not remembered: the next run tries again


def test_run_carries_on_past_a_failing_lab(monkeypatch):
    monkeypatch.setattr(trial_links, "service_client", lambda: _FakeSvc())
    monkeypatch.setattr(trial_links, "active_teams", lambda: {"a", "b", "c"})
    monkeypatch.setattr(trial_links, "_lab_papers", lambda _s, team: team)
    done = []

    def link(team, _papers, lookup, use_pubmed):
        assert use_pubmed  # the daily run checks PubMed too
        if team == "b":
            raise RuntimeError("PostgREST 503")
        done.append(team)
        return trial_links.Linked(1, set())

    monkeypatch.setattr(trial_links, "link_papers", link)
    monkeypatch.setattr(trial_links, "fetch_full_texts", lambda *_a: None)
    with pytest.raises(SystemExit, match="1 lab"):
        trial_links.run()
    assert done == ["a", "c"]


def test_link_paper_does_nothing_for_labs_without_the_feature(monkeypatch):
    monkeypatch.setattr(trial_links, "active_teams", lambda: {"other-lab"})
    monkeypatch.setattr(trial_links, "service_client", lambda: pytest.fail("must not read"))
    monkeypatch.setattr(trial_links, "link_papers", lambda *_a, **_k: pytest.fail("must not link"))
    _real_link_paper("lab", "p1")


def test_link_paper_links_for_labs_with_the_feature(monkeypatch):
    monkeypatch.setattr(trial_links, "active_teams", lambda: {"lab"})
    monkeypatch.setattr(trial_links, "service_client", lambda: _FakeSvc({"papers": [{"id": "p1"}]}))
    got = []

    def link(team, papers):
        got.append((team, papers))
        return trial_links.Linked(1, {"t1"})

    monkeypatch.setattr(trial_links, "link_papers", link)
    fetched = []
    monkeypatch.setattr(
        trial_links, "fetch_full_texts", lambda team, ts: fetched.append((team, ts))
    )
    _real_link_paper("lab", "p1")
    assert got == [("lab", [{"id": "p1"}])]
    assert fetched == [("lab", {"t1"})]  # its full text, without a click


class _UpdatingSvc(_FakeSvc):
    """_FakeSvc that also records updates with their filters."""

    def __init__(self, reads=None):
        super().__init__(reads)
        self.updates: list[tuple[str, dict, list]] = []

    def table(self, name):
        q = super().table(name)
        svc = self

        class U:
            def __init__(self, fields):
                self.fields, self.filters = fields, []

            def eq(self, col, val):
                self.filters.append((col, val))
                return self

            def execute(self):
                svc.updates.append((name, self.fields, self.filters))
                return SimpleNamespace(data=[])

        q.update = lambda fields: U(fields)
        return q


def test_link_papers_by_pubmed(monkeypatch):
    svc = _UpdatingSvc()
    monkeypatch.setattr(trial_links, "service_client", lambda: svc)
    monkeypatch.setattr(
        trial_links,
        "_lab_trials",
        lambda _s, _t: {
            "NCT02032823": {"id": "t-oly", "nct_id": "NCT02032823", "acronym": "OlympiA"},
            "NCT00000009": {"id": "t-gone", "nct_id": "NCT00000009", "acronym": None},
        },
    )
    # p2 already has a suggestion (name in title); p3 a link someone rejected.
    monkeypatch.setattr(
        trial_links,
        "_decided",
        lambda _s, _t, _ids: {("p2", "t-oly"): "suggested", ("p3", "t-oly"): "rejected"},
    )
    monkeypatch.setattr(trial_links, "_removed", lambda _s, _t: {"t-gone"})
    asked = []

    def naming(nct):
        asked.append(nct)
        return 3, [
            SimpleNamespace(doi="10.1/os", pubtypes=("Journal Article",)),
            SimpleNamespace(doi="10.1/sugg", pubtypes=()),
            SimpleNamespace(doi="10.1/rej", pubtypes=()),
            SimpleNamespace(doi="10.1/review", pubtypes=("Journal Article", "Review")),
        ]

    monkeypatch.setattr(trial_links.pubmed, "papers_naming", naming)
    monkeypatch.setattr(trial_links, "_PUBMED_PAUSE", 0)
    papers = [
        {"id": "p1", "title": "Overall survival", "abstract": "No NCT here.", "doi": "10.1/OS"},
        {"id": "p2", "title": "OlympiA final", "abstract": None, "doi": "10.1/sugg"},
        {"id": "p3", "title": "Rejected", "abstract": None, "doi": "10.1/rej"},
        {"id": "p4", "title": "Unrelated", "abstract": None, "doi": "10.1/other"},
        {"id": "p5", "title": "A review", "abstract": None, "doi": "10.1/review"},
    ]
    linked = trial_links.link_papers("lab", papers, use_pubmed=True)

    assert asked == ["NCT02032823"]  # not the trial the lab took off its list
    (links,) = [rows for name, rows in svc.upserts if name == "paper_trials"]
    assert [(r["paper_id"], r["source"], r["status"]) for r in links] == [
        ("p1", "pubmed", "auto"),  # DOI matched whatever its case
        ("p5", "pubmed", "suggested"),  # a review isn't the trial's results
    ]
    # The suggestion PubMed backs up becomes automatic, only while still a suggestion.
    [(table, fields, filters)] = svc.updates
    assert table == "paper_trials" and fields == {"source": "pubmed", "status": "auto"}
    assert ("paper_id", "p2") in filters and ("status", "suggested") in filters
    assert linked == trial_links.Linked(3, {"t-oly"})
    # Without use_pubmed (one posted paper), PubMed isn't asked.
    monkeypatch.setattr(trial_links.pubmed, "papers_naming", lambda _n: pytest.fail("no PubMed"))
    trial_links.link_papers("lab", papers)


def test_pubmed_dois_stops_asking_once_pubmed_fails(monkeypatch):
    calls = []

    def down(nct):
        calls.append(nct)
        raise trial_links.pubmed.PubMedError("down")

    monkeypatch.setattr(trial_links.pubmed, "papers_naming", down)
    lookup = trial_links.Lookup()
    assert trial_links.pubmed_dois("NCT00000001", lookup) == {}
    assert trial_links.pubmed_dois("NCT00000002", lookup) == {}
    assert calls == ["NCT00000001"]
    assert lookup.pubmed == {}  # not remembered: the next run asks again


def test_fetch_full_texts_carries_on_past_a_failing_trial(monkeypatch):
    from api import trial_extract

    done = []

    def fetch(team, trial):
        if trial == "t1":
            raise RuntimeError("Europe PMC down")
        done.append((team, trial))

    monkeypatch.setattr(trial_extract, "fetch_open_access", fetch)
    monkeypatch.setattr(trial_links, "service_client", lambda: _FakeSvc())
    trial_links.fetch_full_texts("lab", {"t2", "t1", "t3"})
    assert done == [("lab", "t2"), ("lab", "t3")]


# --- the API ---------------------------------------------------------------------

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


# --- classification (PR 2) ----------------------------------------------------------

from api import trial_classify  # noqa: E402


def test_registry_digest_carries_what_classification_needs():
    digest = json.loads(trial_classify.registry_digest(_fixture("NCT03036488")["protocolSection"]))
    assert digest["conditions"] == ["Triple Negative Breast Neoplasms"]
    assert {a["type"] for a in digest["arms"]} == {"EXPERIMENTAL", "ACTIVE_COMPARATOR"}
    assert any(i["name"] == "Pembrolizumab" for i in digest["interventions"])
    assert "eligibility" in digest


class _FakeAnthropic:
    def __init__(self, parsed, stop_reason="end_turn"):
        self.parsed, self.stop_reason, self.calls = parsed, stop_reason, []
        self.messages = self

    def __call__(self, **_k):
        return self

    def parse(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(parsed_output=self.parsed, stop_reason=self.stop_reason)


def _with_claude(monkeypatch, fake):
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", fake)
    monkeypatch.setattr(
        trial_classify,
        "get_settings",
        lambda: SimpleNamespace(anthropic_api_key="k", anthropic_model="m"),
    )


def test_classify_orders_and_dedupes(monkeypatch):
    C = trial_classify.Classification
    fake = _FakeAnthropic(
        C(
            settings=["adjuvant", "neoadjuvant", "adjuvant"],
            patient_groups=["tnbc"],
            therapy_classes=["chemotherapy", "immunotherapy"],
        )
    )
    _with_claude(monkeypatch, fake)
    out = trial_classify.classify(_fixture("NCT03036488")["protocolSection"])
    assert out.settings == ["neoadjuvant", "adjuvant"]
    assert out.therapy_classes == ["immunotherapy", "chemotherapy"]
    (call,) = fake.calls
    assert call["output_format"] is C
    assert "<registry_record>" in call["messages"][0]["content"]


def test_classify_gives_up_quietly(monkeypatch):
    _with_claude(monkeypatch, _FakeAnthropic(None, stop_reason="max_tokens"))
    assert trial_classify.classify({}) is None
    monkeypatch.setattr(
        trial_classify, "get_settings", lambda: SimpleNamespace(anthropic_api_key="")
    )
    assert trial_classify.classify({}) is None


def test_classify_lab_claims_and_fills_only_pending_trials(monkeypatch):
    svc = _FakeSvc(
        {
            "trial_posts": [{"trial_id": "t1"}, {"trial_id": "t2"}],
            # A person did t1. Reads of trial_facts also answer _claim's update,
            # which only needs to come back non-empty.
            "trial_facts": [
                {
                    "trial_id": "t1",
                    "classified_by": "person",
                    "classify_attempts": 0,
                    "classify_claimed_at": None,
                }
            ],
            "trials": [{"registry": {"identificationModule": {}}}],
        }
    )
    monkeypatch.setattr(trial_classify, "service_client", lambda: svc)
    C = trial_classify.Classification
    seen = []

    def classify(reg):
        seen.append(reg)
        return C(settings=["metastatic"], patient_groups=[], therapy_classes=["adc"])

    monkeypatch.setattr(trial_classify, "classify", classify)
    assert trial_classify.classify_lab("lab") == 1
    assert len(seen) == 1
    # The placeholder row carries no short name: the registry's shows until a
    # person sets one.
    assert svc.upserts == [("trial_facts", {"team_id": "lab", "trial_id": "t2"})]


def test_pending_skips_given_up_and_claimed_trials():
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    row = {"classified_by": None, "classify_attempts": 0, "classify_claimed_at": None}
    svc = _FakeSvc(
        {
            "trial_posts": [{"trial_id": t} for t in ("new", "retry", "gave-up", "busy", "stale")],
            "trial_facts": [
                {
                    **row,
                    "trial_id": "retry",
                    "classify_attempts": 1,
                    "classify_claimed_at": (now - timedelta(hours=1)).isoformat(),
                },
                {**row, "trial_id": "gave-up", "classify_attempts": trial_classify.MAX_ATTEMPTS},
                {
                    **row,
                    "trial_id": "busy",
                    "classify_attempts": 1,
                    "classify_claimed_at": now.isoformat(),
                },
                {
                    **row,
                    "trial_id": "stale",
                    "classify_attempts": 2,
                    "classify_claimed_at": (now - timedelta(minutes=30)).isoformat(),
                },
            ],
        }
    )
    assert trial_classify._pending(svc, "lab") == [("new", 0), ("retry", 1), ("stale", 2)]


def test_lab_trials_match_the_labs_short_name_too():
    svc = _FakeSvc(
        {
            "trial_posts": [
                {
                    "trial_id": "t",
                    "trials": {"id": "t", "nct_id": "NCT02620280", "acronym": "NeoTRIPaPDL1"},
                }
            ],
            "trial_facts": [{"trial_id": "t", "acronym": "NeoTRIP"}],
        }
    )
    trials = trial_links._lab_trials(svc, "lab")
    assert trials["NCT02620280"]["names"] == ["NeoTRIP", "NeoTRIPaPDL1"]


def test_a_malformed_nct_id_doesnt_stop_pubmed_for_the_rest(monkeypatch):
    def naming(nct):
        if nct == "nct1":
            raise ValueError("not an NCT ID")
        return 1, [SimpleNamespace(doi="10.1/x", pubtypes=())]

    monkeypatch.setattr(trial_links.pubmed, "papers_naming", naming)
    monkeypatch.setattr(trial_links, "_PUBMED_PAUSE", 0)
    lookup = trial_links.Lookup()
    assert trial_links.pubmed_dois("nct1", lookup) == {}
    assert trial_links.pubmed_dois("NCT00000002", lookup) == {"10.1/x": False}


def _pubmed_lab(monkeypatch, listed):
    """A lab with trials t1..t4 whose PubMed lists are `listed` {trial: [doi]}."""
    svc = _UpdatingSvc()
    monkeypatch.setattr(trial_links, "service_client", lambda: svc)
    trials = {f"NCT0000000{i}": {"id": f"t{i}", "nct_id": f"NCT0000000{i}"} for i in range(1, 5)}
    monkeypatch.setattr(trial_links, "_lab_trials", lambda _s, _t: trials)
    monkeypatch.setattr(trial_links, "_decided", lambda *_a: {})
    monkeypatch.setattr(trial_links, "_removed", lambda *_a: set())
    asked = []

    def naming(nct):
        asked.append(nct)
        dois = listed.get(trials[nct]["id"], [])
        return len(dois), [SimpleNamespace(doi=d, pubtypes=()) for d in dois]

    monkeypatch.setattr(trial_links.pubmed, "papers_naming", naming)
    monkeypatch.setattr(trial_links, "_PUBMED_PAUSE", 0)
    return svc, asked


def test_a_paper_listed_under_several_of_the_labs_trials_is_only_suggested(monkeypatch):
    pooled = ["10.1/pooled"]
    svc, _ = _pubmed_lab(monkeypatch, {"t1": pooled, "t2": pooled, "t3": pooled})
    paper = {"id": "p", "title": "Pooled analysis", "abstract": None, "doi": "10.1/pooled"}
    linked = trial_links.link_papers("lab", [paper], use_pubmed=True)
    (links,) = [rows for name, rows in svc.upserts if name == "paper_trials"]
    assert {r["status"] for r in links} == {"suggested"} and len(links) == 3
    assert linked.trials == set()  # nothing fetched, nothing queued


def test_a_new_trial_asks_pubmed_about_that_trial_only(monkeypatch):
    _, asked = _pubmed_lab(monkeypatch, {})
    paper = {"id": "p", "title": "x", "abstract": None, "doi": "10.1/x"}
    trial_links.link_papers("lab", [paper], use_pubmed=True, pubmed_trials={"t2"})
    assert asked == ["NCT00000002"]


def test_fetch_full_texts_takes_a_few_trials_at_a_time_and_stamps_them(monkeypatch):
    from api import trial_extract

    svc = _FakeSvc()
    monkeypatch.setattr(trial_links, "service_client", lambda: svc)
    monkeypatch.setattr(trial_links, "FETCH_PER_RUN", 2)
    done = []
    monkeypatch.setattr(trial_extract, "fetch_open_access", lambda team, t: done.append(t))
    trial_links.fetch_full_texts("lab", {"t3", "t1", "t2"})
    assert done == ["t1", "t2"]  # the daily job takes the rest
    stamped = [rows["trial_id"] for name, rows in svc.upserts if name == "trial_facts"]
    assert stamped == ["t1", "t2"]
