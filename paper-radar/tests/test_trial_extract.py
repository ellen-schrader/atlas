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
    assert call["messages"][0]["content"][1]["cache_control"] == {"type": "ephemeral"}
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
    monkeypatch.setattr(te, "claim", lambda *_a: False)
    monkeypatch.setattr(te, "run", lambda *_a: pytest.fail("must not run"))
    r = client.post("/trials/t1/extract", json={"team_id": "lab"}, headers=AUTH)
    assert r.status_code == 409


def test_extract_endpoint_starts_a_run(monkeypatch):
    monkeypatch.setattr(trials_api, "_require_lab_trial", lambda *_a: "u1")
    monkeypatch.setattr(trials_api._extract_limiter, "check", lambda _u: None)
    monkeypatch.setattr(te, "claim", lambda *_a: True)
    ran = []
    monkeypatch.setattr(te, "run", lambda team, trial: ran.append((team, trial)))
    r = client.post("/trials/t1/extract", json={"team_id": "lab"}, headers=AUTH)
    assert r.status_code == 202
    assert ran == [("lab", "t1")]


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
