"""Clinical trials, PR 4: Europe PMC fetching and Claude extraction (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from api import trial_extract as te

# --- Europe PMC ------------------------------------------------------------------


def test_open_access_pmcid(monkeypatch):
    asked = []

    def get(path, limit):
        asked.append(path)
        return json.dumps(
            {
                "resultList": {
                    "result": [{"pmcid": "PMC12283416", "isOpenAccess": "Y", "inEPMC": "Y"}]
                }
            }
        ).encode()

    monkeypatch.setattr(te, "_epmc_get", get)
    assert te.open_access_pmcid("10.1038/s41591-025-03725-4") == "PMC12283416"
    assert "DOI%3A%2210.1038%2Fs41591-025-03725-4%22" in asked[0]


def test_open_access_pmcid_refuses_bad_dois_and_closed_papers(monkeypatch):
    monkeypatch.setattr(te, "_epmc_get", lambda *_a, **_k: pytest.fail("must not ask"))
    assert te.open_access_pmcid("not a doi") is None
    assert te.open_access_pmcid("10.1/x y") is None
    closed = {"resultList": {"result": [{"pmcid": "PMC1", "isOpenAccess": "N", "inEPMC": "Y"}]}}
    monkeypatch.setattr(te, "_epmc_get", lambda *_a, **_k: json.dumps(closed).encode())
    assert te.open_access_pmcid("10.1000/abc") is None
    # A malformed PMCID from the API isn't trusted either.
    odd = {"resultList": {"result": [{"pmcid": "../../x", "isOpenAccess": "Y", "inEPMC": "Y"}]}}
    monkeypatch.setattr(te, "_epmc_get", lambda *_a, **_k: json.dumps(odd).encode())
    assert te.open_access_pmcid("10.1000/abc") is None


def test_full_text_xml_checks_what_it_gets(monkeypatch):
    monkeypatch.setattr(te, "_epmc_get", lambda *_a, **_k: pytest.fail("must not ask"))
    assert te.full_text_xml("PMC1/../x") is None
    monkeypatch.setattr(te, "_epmc_get", lambda *_a, **_k: b"%PDF-1.4 not xml")
    assert te.full_text_xml("PMC1") is None
    monkeypatch.setattr(te, "_epmc_get", lambda *_a, **_k: b'\n<?xml version="1.0"?><article/>')
    assert te.full_text_xml("PMC1").endswith(b"<article/>")


def test_pmc_copy_tells_open_access_from_manuscripts(monkeypatch):
    manuscript = {"resultList": {"result": [{"pmcid": "PMC9", "isOpenAccess": "N", "inEPMC": "Y"}]}}
    monkeypatch.setattr(te, "_epmc_get", lambda *_a, **_k: json.dumps(manuscript).encode())
    assert te.pmc_copy("10.1056/x") == ("PMC9", False)
    assert te.open_access_pmcid("10.1056/x") is None
    none = {"resultList": {"result": [{"isOpenAccess": "N", "inEPMC": "N"}]}}
    monkeypatch.setattr(te, "_epmc_get", lambda *_a, **_k: json.dumps(none).encode())
    assert te.pmc_copy("10.1056/x") == (None, False)


def _opendata(files):
    """A fake PMC dataset bucket: path → body (missing paths answer None)."""
    asked = []

    def get(path, limit):
        asked.append(path)
        return files.get(path)

    return get, asked


def _meta(pmcid, **kw):
    return json.dumps({"pmcid": pmcid, "is_retracted": False, "license_code": "TDM", **kw}).encode()


def test_manuscript_xml_takes_the_latest_version(monkeypatch):
    get, asked = _opendata(
        {
            "PMC9.1/PMC9.1.json": _meta("PMC9"),
            "PMC9.2/PMC9.2.json": _meta("PMC9"),
            "PMC9.2/PMC9.2.xml": b"<!DOCTYPE article><article>v2</article>",
        }
    )
    monkeypatch.setattr(te, "_opendata_get", get)
    assert te.manuscript_xml("PMC9").endswith(b"<article>v2</article>")
    assert asked[-1] == "PMC9.2/PMC9.2.xml"


def test_manuscript_xml_only_takes_what_may_be_reused(monkeypatch):
    for meta in (
        _meta("PMC9", is_retracted=True),
        _meta("PMC9", license_code="NO-CC CODE"),
        _meta("PMC8"),  # the bucket describing another article
        b"not json",
    ):
        get, _ = _opendata({"PMC9.1/PMC9.1.json": meta, "PMC9.1/PMC9.1.xml": b"<article/>"})
        monkeypatch.setattr(te, "_opendata_get", get)
        assert te.manuscript_xml("PMC9") is None, meta
    # Open access under any licence is fine.
    get, _ = _opendata(
        {
            "PMC9.1/PMC9.1.json": _meta("PMC9", license_code="CC BY", is_pmc_openaccess=True),
            "PMC9.1/PMC9.1.xml": b"<article/>",
        }
    )
    monkeypatch.setattr(te, "_opendata_get", get)
    assert te.manuscript_xml("PMC9") == b"<article/>"
    monkeypatch.setattr(te, "_opendata_get", lambda *_a, **_k: pytest.fail("must not ask"))
    assert te.manuscript_xml("PMC9/../x") is None


class _OpenAccessSvc:
    """paper_trials and trial_sources reads; records uploads and source rows."""

    def __init__(self, links, sources=()):
        self.rows = {"paper_trials": links, "trial_sources": list(sources)}
        self.storage = _Storage({})
        self.upserted: list[dict] = []

    def table(self, name):
        svc = self

        class Q:
            def __getattr__(self, _a):
                return lambda *a, **k: self

            def upsert(self, row, **_k):
                svc.upserted.append(row)
                return self

            def execute(self):
                return SimpleNamespace(data=svc.rows.get(name, []))

        return Q()


def test_fetch_open_access_takes_manuscripts_and_says_what_it_left_out(monkeypatch):
    def link(pid, status, doi):
        return {"paper_id": pid, "status": status, "papers": {"id": pid, "doi": doi, "title": pid}}

    svc = _OpenAccessSvc(
        [
            link("oa", "auto", "10.1/oa"),
            link("ms", "confirmed", "10.1/ms"),
            link("closed", "auto", "10.1/closed"),
            link("waiting", "suggested", "10.1/waiting"),
            link("held", "auto", "10.1/held"),
        ],
        sources=[{"paper_id": "held"}],
    )
    monkeypatch.setattr(te, "service_client", lambda: svc)
    copies = {"10.1/oa": ("PMC1", True), "10.1/ms": ("PMC2", False)}
    monkeypatch.setattr(te, "pmc_copy", lambda doi: copies.get(doi, (None, False)))
    monkeypatch.setattr(te, "full_text_xml", lambda pmcid: b"<article>oa</article>")
    monkeypatch.setattr(te, "manuscript_xml", lambda pmcid: b"<article>ms</article>")

    out = te.fetch_open_access("lab", "t1")

    assert sorted(out["fetched"]) == ["ms", "oa"]
    assert out["closed"] == ["closed"]
    assert out["have"] == ["held"]
    assert out["unconfirmed"] == ["waiting"]  # never fetched until someone confirms it
    names = sorted(r["filename"] for r in svc.upserted)
    assert names == ["PMC1 full text (Europe PMC)", "PMC2 author manuscript (PMC)"]


def test_redirects_are_never_followed():
    assert (
        te._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.test/")
        is None
    )


# --- reading the sources ----------------------------------------------------------


class _Storage:
    def __init__(self, files):
        self.files = files
        self.uploads = []

    def from_(self, _bucket):
        return self

    def download(self, path):
        return self.files[path]

    def upload(self, path, data, _opts):
        self.uploads.append(path)


def test_documents_build_blocks_and_check_pdfs():
    svc = SimpleNamespace(
        storage=_Storage(
            {"a.pdf": b"%PDF-1.7 ...", "b.xml": b"<article>t</article>", "c.pdf": b"<html>"}
        )
    )
    blocks, listing = te._documents(
        svc,
        [
            {
                "storage_path": "a.pdf",
                "filename": "Main.pdf",
                "kind": "paper",
                "media_type": "application/pdf",
            },
            {
                "storage_path": "b.xml",
                "filename": "PMC1",
                "kind": "paper",
                "media_type": "application/xml",
            },
        ],
    )
    assert [b["source"]["type"] for b in blocks] == ["base64", "text"]
    assert listing == ["Document 1: Main.pdf (paper)", "Document 2: PMC1 (paper)"]
    with pytest.raises(te.ExtractionError, match="isn't a PDF"):
        te._documents(
            svc,
            [
                {
                    "storage_path": "c.pdf",
                    "filename": "c.pdf",
                    "kind": "paper",
                    "media_type": "application/pdf",
                }
            ],
        )


def test_documents_refuse_more_than_the_api_takes(monkeypatch):
    monkeypatch.setattr(te, "MAX_REQUEST_BYTES", 10)
    svc = SimpleNamespace(storage=_Storage({"a": b"%PDF-" + b"x" * 20}))
    with pytest.raises(te.ExtractionError, match="too large"):
        te._documents(
            svc,
            [
                {
                    "storage_path": "a",
                    "filename": "a",
                    "kind": "paper",
                    "media_type": "application/pdf",
                }
            ],
        )


# --- asking Claude -----------------------------------------------------------------

VALID = {
    "pico": {"population": "P", "intervention": "I", "comparator": "C", "outcome": "O"},
    "design": {
        "phase": "Phase III",
        "randomisation_ratio": "1:1",
        "blinding": "double-blind",
        "analysis_population": None,
        "data_cutoff": None,
        "source": None,
    },
    "arms": [],
    "schedule": [],
    "endpoints": [],
    "adverse_events": [],
    "enrolment": {
        "n_screened": 455,
        "n_randomised": 333,
        "n_analysed": 333,
        "dimensions": [],
        "source": None,
    },
    "context": [],
    "caveats": "A note.",
}


class _Stream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.msg


class _Client:
    """Answers each request with the next of `answers`: a dict is recorded as
    the tool call, None means no tool call."""

    def __init__(self, answers, stop_reason="end_turn"):
        self.answers = list(answers)
        self.calls = []
        self.stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=self)

    def stream(self, **kw):
        self.calls.append(kw)
        answer = self.answers.pop(0)
        content = (
            [SimpleNamespace(type="tool_use", name=te.TOOL, id="tu1", input=answer)]
            if answer is not None
            else [SimpleNamespace(type="text", text="Here you go")]
        )
        usage = SimpleNamespace(
            input_tokens=1000,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            output_tokens=500,
        )
        return _Stream(
            SimpleNamespace(
                stop_reason=self.stop_reason, content=content, usage=usage, model="claude-opus-5-5"
            )
        )


def _with_client(monkeypatch, client):
    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", lambda **_k: client)
    monkeypatch.setattr(te, "get_settings", lambda: SimpleNamespace(anthropic_api_key="k"))


def test_extract_records_through_one_tool_call(monkeypatch):
    client = _Client([VALID])
    _with_client(monkeypatch, client)
    blocks = [
        {"type": "document", "source": {"type": "text", "media_type": "text/plain", "data": "x"}}
    ]
    result, cost, model = te.extract({}, blocks, ["Document 1: x (paper)"])

    (call,) = client.calls
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == [{"model": "claude-opus-4-8"}]
    assert call["tool_choice"] == {"type": "auto"}  # Opus 5.5 can't be forced
    assert [t["name"] for t in call["tools"]] == [te.TOOL]
    assert "strict" not in call["tools"][0]  # the grammar limit
    # One read of the documents: no cache write (it would cost 1.25× for nothing).
    assert not any("cache_control" in b for b in call["messages"][0]["content"])
    assert result.enrolment.n_randomised == 333
    assert model == "claude-opus-5-5"
    assert cost == pytest.approx(1000 / 1e6 * 4 + 500 / 1e6 * 20)


def test_extract_retries_once_with_the_schema_error(monkeypatch):
    bad = {**VALID, "design": {**VALID["design"], "blinding": "sort of"}}
    client = _Client([bad, VALID])
    _with_client(monkeypatch, client)
    result, _cost, _model = te.extract({}, [], [])
    assert result.design.blinding == "double-blind"
    retry = client.calls[1]["messages"]
    assert retry[-1]["content"][0]["type"] == "tool_result"
    assert retry[-1]["content"][0]["is_error"] is True
    assert "blinding" in retry[-1]["content"][0]["content"]


def test_extract_gives_up_after_two_bad_answers(monkeypatch):
    bad = {**VALID, "arms": "none"}
    _with_client(monkeypatch, _Client([bad, bad]))
    with pytest.raises(te.ExtractionError, match="didn't fit"):
        te.extract({}, [], [])


def test_extract_needs_the_tool_call(monkeypatch):
    _with_client(monkeypatch, _Client([None]))
    with pytest.raises(te.ExtractionError, match="didn't record"):
        te.extract({}, [], [])


@pytest.mark.parametrize(("stop", "message"), [("refusal", "declined"), ("max_tokens", "cut off")])
def test_extract_reports_refusals_and_truncation(monkeypatch, stop, message):
    _with_client(monkeypatch, _Client([VALID], stop_reason=stop))
    with pytest.raises(te.ExtractionError, match=message):
        te.extract({}, [], [])


def test_cost_counts_cache_reads_cheaply():
    usage = SimpleNamespace(
        input_tokens=0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=1_000_000,
        output_tokens=0,
    )
    assert te._cost(usage) == pytest.approx(0.2)  # 0.05 × $4


# --- the background run ---------------------------------------------------------------


class _Svc:
    """trial_sources / trials reads; records updates and deletes."""

    def __init__(self, sources, files):
        self.sources = sources
        self.storage = _Storage(files)
        self.updates: list[dict] = []
        self.deletes: list[str] = []

    def table(self, name):
        svc = self

        class Q:
            def __getattr__(self, _a):
                return lambda *a, **k: self

            def update(self, fields):
                svc.updates.append(fields)
                return self

            def delete(self):
                svc.deletes.append(name)
                return self

            def execute(self):
                data = {"trial_sources": svc.sources, "trials": [{"registry": {}}]}.get(name, [])
                return SimpleNamespace(data=data)

        return Q()


def test_run_without_sources_fails_with_a_reason(monkeypatch):
    svc = _Svc([], {})
    monkeypatch.setattr(te, "service_client", lambda: svc)
    te.run("lab", "t1")
    assert svc.updates[-1]["extraction_status"] == "failed"
    assert "upload a PDF" in svc.updates[-1]["extraction_error"]


def test_run_stores_the_extraction_and_which_documents_it_read(monkeypatch):
    svc = _Svc(
        [
            {
                "id": "s1",
                "storage_path": "a.pdf",
                "filename": "a.pdf",
                "kind": "paper",
                "media_type": "application/pdf",
            }
        ],
        {"a.pdf": b"%PDF-1.7"},
    )
    monkeypatch.setattr(te, "service_client", lambda: svc)
    _with_client(monkeypatch, _Client([VALID]))
    te.run("lab", "t1")
    done = svc.updates[-1]
    assert done["extraction_status"] == "done"
    assert done["extraction_sources"] == ["s1"]
    assert done["extraction"]["enrolment"]["n_randomised"] == 333
    assert "trial_fact_reviews" in svc.deletes  # a new extraction replaces the checks
    assert svc.updates.index(done) == len(svc.updates) - 1  # cleared before "done"


# --- the API ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

import api.trials as trials_api  # noqa: E402
from api.app import app  # noqa: E402

client = TestClient(app)
AUTH = {"Authorization": "Bearer t"}


def test_extract_endpoint_refuses_a_second_run(monkeypatch):
    monkeypatch.setattr(trials_api, "_require_lab_trial", lambda *_a: "u1")
    monkeypatch.setattr(trials_api._extract_limiter, "check", lambda _u: None)
    monkeypatch.setattr(trials_api, "service_client", lambda: None)
    monkeypatch.setattr(te, "over_budget", lambda _s, _t: None)
    monkeypatch.setattr(te, "claim", lambda *_a: False)
    monkeypatch.setattr(te, "run", lambda *_a: pytest.fail("must not run"))
    r = client.post("/trials/t1/extract", json={"team_id": "lab", "mode": "now"}, headers=AUTH)
    assert r.status_code == 409


def test_extract_endpoint_now_starts_a_run(monkeypatch):
    monkeypatch.setattr(trials_api, "_require_lab_trial", lambda *_a: "u1")
    monkeypatch.setattr(trials_api._extract_limiter, "check", lambda _u: None)
    monkeypatch.setattr(trials_api, "service_client", lambda: None)
    monkeypatch.setattr(te, "over_budget", lambda _s, _t: None)
    monkeypatch.setattr(te, "claim", lambda *_a: True)
    ran = []
    monkeypatch.setattr(te, "run", lambda team, trial: ran.append((team, trial)))
    r = client.post("/trials/t1/extract", json={"team_id": "lab", "mode": "now"}, headers=AUTH)
    assert r.status_code == 202
    assert r.json() == {"status": "running"}
    assert ran == [("lab", "t1")]


def test_extract_endpoint_now_respects_the_budget(monkeypatch):
    monkeypatch.setattr(trials_api, "_require_lab_trial", lambda *_a: "u1")
    monkeypatch.setattr(trials_api._extract_limiter, "check", lambda _u: None)
    monkeypatch.setattr(trials_api, "service_client", lambda: None)
    used = "This month's extraction budget ($10) is used."
    monkeypatch.setattr(te, "over_budget", lambda _s, _t: used)
    monkeypatch.setattr(te, "claim", lambda *_a: pytest.fail("must not claim"))
    r = client.post("/trials/t1/extract", json={"team_id": "lab", "mode": "now"}, headers=AUTH)
    assert r.status_code == 402


def test_extract_endpoint_queues_by_default(monkeypatch):
    monkeypatch.setattr(trials_api, "_require_lab_trial", lambda *_a: "u1")
    monkeypatch.setattr(trials_api._extract_limiter, "check", lambda _u: None)
    queued = []
    monkeypatch.setattr(te, "queue", lambda team, trial: queued.append((team, trial)) or True)
    monkeypatch.setattr(te, "run", lambda *_a: pytest.fail("must not run now"))
    r = client.post("/trials/t1/extract", json={"team_id": "lab"}, headers=AUTH)
    assert r.json() == {"status": "queued"}
    assert queued == [("lab", "t1")]


def test_endpoints_404_for_a_trial_not_on_the_list(monkeypatch):
    monkeypatch.setattr(trials_api, "_require_feature", lambda _t, _team: "u1")

    class Empty:
        def __getattr__(self, _a):
            return lambda *a, **k: self

        def execute(self):
            return SimpleNamespace(data=[])

    monkeypatch.setattr(trials_api, "user_client", lambda _t: Empty())
    for path in ("/trials/t1/extract", "/trials/t1/open-access"):
        r = client.post(path, json={"team_id": "lab"}, headers=AUTH)
        assert r.status_code == 404


# --- a collection's "Get data" ----------------------------------------------------------


class _FactsSvc:
    """trial_facts and trial_sources reads for get_data()."""

    def __init__(self, facts, sources):
        self.rows = {"trial_facts": facts, "trial_sources": sources}

    def table(self, name):
        rows = self.rows.get(name, [])

        class Q:
            def __getattr__(self, _a):
                return lambda *a, **k: self

            def execute(self):
                return SimpleNamespace(data=rows)

        return Q()


def test_get_data_leaves_trials_with_data_alone(monkeypatch):
    svc = _FactsSvc(
        facts=[{"trial_id": "has", "extracted_at": "2026-10-01T00:00:00Z"}, {"trial_id": "files"}],
        sources=[{"trial_id": "files"}, {"trial_id": "busy"}],
    )
    monkeypatch.setattr(te, "service_client", lambda: svc)
    looked_up = []

    def open_access(_team, trial):
        looked_up.append(trial)
        return {"fetched": ["Paper"] if trial == "open" else [], "closed": [], "have": []}

    monkeypatch.setattr(te, "fetch_open_access", open_access)
    queued = []
    monkeypatch.setattr(te, "queue", lambda _team, trial: queued.append(trial) or trial != "busy")
    out = te.get_data("lab", ["has", "files", "open", "closed", "busy"])
    assert out == {"queued": ["files", "open"], "need_pdf": ["closed"], "skipped": ["has", "busy"]}
    assert "has" not in queued  # re-extracting would cost money and wipe the checks
    assert sorted(looked_up) == ["closed", "open"]  # only trials with no files


def _lab_has(monkeypatch, trial_ids):
    monkeypatch.setattr(trials_api, "_require_feature", lambda _t, _team: "u1")
    monkeypatch.setattr(trials_api._get_data_limiter, "check", lambda _u: None)
    monkeypatch.setattr(trials_api, "service_client", lambda: None)
    rows = [{"trial_id": t} for t in trial_ids]
    monkeypatch.setattr(
        trials_api,
        "user_client",
        lambda _t: SimpleNamespace(table=lambda _n: _Rows(rows)),
    )


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def __getattr__(self, _a):
        return lambda *a, **k: self

    def execute(self):
        return SimpleNamespace(data=self.rows)


def test_get_data_endpoint_queues_in_one_request(monkeypatch):
    _lab_has(monkeypatch, ["t1", "t2"])
    monkeypatch.setattr(te, "over_budget", lambda _s, _t: None)
    monkeypatch.setattr(
        te, "get_data", lambda team, ids: {"queued": ids, "need_pdf": [], "skipped": []}
    )
    r = client.post(
        "/trials/get-data", json={"team_id": "lab", "trial_ids": ["t1", "t2", "t1"]}, headers=AUTH
    )
    assert r.status_code == 200
    assert r.json() == {"queued": ["t1", "t2"], "need_pdf": [], "skipped": []}


def test_get_data_endpoint_says_when_the_lab_is_at_its_cap(monkeypatch):
    _lab_has(monkeypatch, ["t1"])
    monkeypatch.setattr(te, "over_budget", lambda _s, _t: "This month's budget is used.")
    monkeypatch.setattr(te, "get_data", lambda *_a: pytest.fail("must not queue"))
    r = client.post("/trials/get-data", json={"team_id": "lab", "trial_ids": ["t1"]}, headers=AUTH)
    assert r.status_code == 402


def test_get_data_endpoint_404s_for_a_trial_not_on_the_list(monkeypatch):
    _lab_has(monkeypatch, ["t1"])
    monkeypatch.setattr(te, "get_data", lambda *_a: pytest.fail("must not queue"))
    r = client.post(
        "/trials/get-data", json={"team_id": "lab", "trial_ids": ["t1", "other"]}, headers=AUTH
    )
    assert r.status_code == 404
