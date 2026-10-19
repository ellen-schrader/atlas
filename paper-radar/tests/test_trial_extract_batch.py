"""Clinical trials, PR 7: trimmed full text, budgets, and batched extraction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from api import trial_extract as te
from api import trial_extract_batch as tb
from paper_radar.trials import jats

# --- JATS → text --------------------------------------------------------------------

ARTICLE = b"""<?xml version="1.0"?>
<article><front><article-meta>
  <title-group><article-title>Atezolizumab in TNBC</article-title></title-group>
  <contrib-group><contrib><name>Someone</name></contrib></contrib-group>
  <abstract><p>pCR 58% vs 41%.</p></abstract>
</article-meta></front>
<body>
  <sec><title>Results</title>
    <p>Baseline characteristics are in <xref>Table 1</xref>.
      <table-wrap><label>Table 1</label><caption><p>Baseline</p></caption>
        <table><tr><th>Stage</th><th>Atezo</th></tr><tr><td>II</td><td>118 (72)</td></tr></table>
        <table-wrap-foot><p>ITT population.</p></table-wrap-foot>
      </table-wrap>
    </p>
    <fig><label>Fig. 2</label><caption><p>EFS, HR 0.76</p></caption></fig>
  </sec>
  <sec><title>Competing interests</title><p>Lots of disclosures.</p></sec>
  <sec><title>References</title><p>1. A paper.</p></sec>
</body>
<back><ref-list><ref>2. Another</ref></ref-list>
  <app><table-wrap><label>Extended Data Table 3</label><caption><p>Safety</p></caption>
    <table><tr><td>Grade 3/4</td><td>70%</td></tr></table></table-wrap></app>
</back></article>"""


def test_jats_keeps_trial_content_and_drops_the_rest():
    t = jats.to_text(ARTICLE)
    assert "# Atezolizumab in TNBC" in t
    assert "pCR 58% vs 41%." in t
    assert "Stage | Atezo" in t and "II | 118 (72)" in t
    assert "ITT population." in t
    assert "[Figure] Fig. 2 EFS, HR 0.76" in t
    assert "Extended Data Table 3" in t and "Grade 3/4 | 70%" in t
    for gone in ("Someone", "disclosures", "A paper", "Another"):
        assert gone not in t


def test_jats_reads_appendices_and_floats_groups_once():
    xml = b"""<article><body><sec><title>Methods</title><p>Randomised.</p></sec></body>
    <back><app-group><app><sec><title>Appendix A</title><p>Eligibility details.</p>
      <sec><title>A.1</title><p>Nested once.</p></sec>
      <table-wrap><label>Table A1</label><table><tr><td>x</td></tr></table></table-wrap>
    </sec></app></app-group></back>
    <floats-group><table-wrap><label>Table 2</label><caption><p>Efficacy</p></caption>
      <table><tr><td>pCR</td><td>58%</td></tr></table></table-wrap></floats-group></article>"""
    t = jats.to_text(xml)
    assert t.count("Nested once.") == 1
    assert t.count("Table A1") == 1
    assert "Eligibility details." in t
    assert "[Table] Table 2 Efficacy" in t and "pCR | 58%" in t


def test_jats_refuses_entity_declarations_and_junk():
    with pytest.raises(jats.NotJats):
        jats.to_text(b'<!DOCTYPE a [<!ENTITY x "xx">]><article><body/></article>')
    with pytest.raises(jats.NotJats):
        jats.to_text(b"not xml")
    with pytest.raises(jats.NotJats):
        jats.to_text(b"<article><front/></article>")  # no body


def test_documents_send_xml_trimmed():
    svc = SimpleNamespace(
        storage=SimpleNamespace(from_=lambda _b: SimpleNamespace(download=lambda _p: ARTICLE))
    )
    blocks, _ = te._documents(
        svc,
        [
            {
                "storage_path": "x",
                "filename": "PMC1",
                "kind": "paper",
                "media_type": "application/xml",
            }
        ],
    )
    data = blocks[0]["source"]["data"]
    assert "<table" not in data and "II | 118 (72)" in data


# --- budget -------------------------------------------------------------------------------


class _Spend:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        rows = self.rows

        class Q:
            def __getattr__(self, _a):
                return lambda *a, **k: self

            def execute(self):
                return SimpleNamespace(data=rows)

        return Q()


def test_budget(monkeypatch):
    monkeypatch.setenv("TRIAL_EXTRACTION_MONTHLY_USD", "1")
    monkeypatch.setattr(te, "committed", lambda _s, _t: 0.0)
    assert te.over_budget(_Spend([{"usd": "0.46"}, {"usd": "0.30"}]), "lab") is None
    assert "budget ($1)" in te.over_budget(_Spend([{"usd": "0.46"}, {"usd": "0.60"}]), "lab")
    # What's out and not billed yet counts too: a batch, or an "Extract now".
    monkeypatch.setattr(te, "committed", lambda _s, _t: 0.30)
    assert "budget ($1)" in te.over_budget(_Spend([{"usd": "0.46"}, {"usd": "0.30"}]), "lab")


# --- the batch job ----------------------------------------------------------------------------


class _Svc:
    def __init__(self, rows):
        self.rows = rows  # trial_facts rows, as the job reads them
        self.updates: list[tuple[str, dict]] = []
        self.inserts: list[tuple[str, dict]] = []

    def table(self, name):
        svc = self

        class Q:
            status = None

            def __getattr__(self, _a):
                return lambda *a, **k: self

            def eq(self, col, val):
                if col == "extraction_status":
                    self.status = val
                return self

            def update(self, fields):
                svc.updates.append((name, fields))
                return self

            def insert(self, row):
                svc.inserts.append((name, row))
                return self

            def execute(self):
                if name == "trial_facts" and self.status:
                    return SimpleNamespace(data=[r for r in svc.rows if r["status"] == self.status])
                return SimpleNamespace(data=[])

        return Q()


def _row(trial, status, attempts=0, batch=None, sources=None):
    return {
        "team_id": "lab",
        "trial_id": trial,
        "status": status,
        "extraction_attempts": attempts,
        "extraction_batch_id": batch,
        "extraction_batch_sources": sources,
        "extraction_queued_at": None,
    }


class _Batches:
    def __init__(self, results=(), status="ended", created=None):
        self.created: list = []
        self._results = list(results)
        self._status = status
        self._created_at = created or datetime.now(UTC)

    def create(self, requests):
        self.created.append(requests)
        return SimpleNamespace(id="batch_1")

    def retrieve(self, _id):
        return SimpleNamespace(processing_status=self._status, created_at=self._created_at)

    def results(self, _id):
        return self._results


def _client(batches):
    return SimpleNamespace(messages=SimpleNamespace(batches=batches))


def _budget(monkeypatch, spent: dict[str, float], cap: float = 5.0):
    monkeypatch.setattr(te, "monthly_cap", lambda: cap)
    monkeypatch.setattr(te, "spent_this_month", lambda _s, team: spent.get(team, 0.0))
    monkeypatch.setattr(te, "committed", lambda _s, _t: 0.0)


def _load_ok(_s, _team, trial):
    if trial == "broken":
        raise RuntimeError("storage said no")
    return [{"id": f"{trial}-s1"}], {}, [], []


def test_submit_sends_queued_trials_of_active_labs_under_budget(monkeypatch):
    svc = _Svc([_row("t1", "queued"), _row("t2", "queued") | {"team_id": "other"}])
    monkeypatch.setattr(tb, "active_teams", lambda: {"lab"})
    _budget(monkeypatch, {})
    monkeypatch.setattr(te, "load", _load_ok)
    batches = _Batches()
    assert tb.submit(svc, _client(batches)) == 1
    [requests] = batches.created
    assert [r["custom_id"] for r in requests] == [tb.custom_id("lab", "t1")]
    assert "fallbacks" not in requests[0]["params"]  # batches take none
    # Claimed first (queued → batched, no batch yet), then given its batch.
    claims = [
        f
        for n, f in svc.updates
        if f == {"extraction_status": "batched", "extraction_batch_id": None}
    ]
    assert len(claims) == 1
    [sent] = [f for n, f in svc.updates if f.get("extraction_batch_id") == "batch_1"]
    assert sent["extraction_batch_sources"] == ["t1-s1"]
    assert sent["extraction_attempts"] == 1
    assert 0 < sent["extraction_estimate_usd"] < 1


def test_an_over_budget_lab_doesnt_hold_up_the_others(monkeypatch):
    rows = [_row(f"a{i}", "queued") | {"team_id": "spent"} for i in range(60)] + [
        _row("b1", "queued")
    ]
    svc = _Svc(rows)
    monkeypatch.setattr(tb, "active_teams", lambda: {"spent", "lab"})
    _budget(monkeypatch, {"spent": 5.0})
    monkeypatch.setattr(te, "load", _load_ok)
    batches = _Batches()
    assert tb.submit(svc, _client(batches)) == 1
    assert [r["custom_id"] for r in batches.created[0]] == [tb.custom_id("lab", "b1")]
    waiting = [f for n, f in svc.updates if "budget" in (f.get("extraction_error") or "")]
    assert len(waiting) == 60  # still queued, told why


def test_estimates_stop_a_batch_overshooting_the_cap(monkeypatch):
    svc = _Svc([_row(f"t{i}", "queued") for i in range(10)])
    monkeypatch.setattr(tb, "active_teams", lambda: {"lab"})
    _budget(monkeypatch, {"lab": 4.85})  # $0.15 left
    monkeypatch.setattr(te, "load", _load_ok)
    monkeypatch.setattr(tb, "estimate_usd", lambda _p: 0.1)
    batches = _Batches()
    assert tb.submit(svc, _client(batches)) == 1  # one fits, the second would overshoot


def test_a_failed_batch_create_puts_claimed_trials_back(monkeypatch):
    svc = _Svc([_row("t1", "queued")])
    monkeypatch.setattr(tb, "active_teams", lambda: {"lab"})
    _budget(monkeypatch, {})
    monkeypatch.setattr(te, "load", _load_ok)

    class Down(_Batches):
        def create(self, requests):
            raise RuntimeError("API down")

    with pytest.raises(RuntimeError):
        tb.submit(svc, _client(Down()))
    assert svc.updates[-1] == (
        "trial_facts",
        {"extraction_status": "queued", "extraction_error": None},
    )


def test_just_queued_trials_wait_for_their_other_files(monkeypatch):
    now = datetime.now(UTC)
    svc = _Svc(
        [
            _row("new", "queued") | {"extraction_queued_at": now.isoformat()},
            _row("old", "queued")
            | {"extraction_queued_at": (now - timedelta(hours=1)).isoformat()},
        ]
    )
    monkeypatch.setattr(tb, "active_teams", lambda: {"lab"})
    _budget(monkeypatch, {})
    monkeypatch.setattr(te, "load", _load_ok)
    batches = _Batches()
    assert tb.submit(svc, _client(batches)) == 1
    assert [r["custom_id"] for r in batches.created[0]] == [tb.custom_id("lab", "old")]


def test_one_unreadable_trial_fails_alone(monkeypatch):
    svc = _Svc([_row("broken", "queued"), _row("t1", "queued")])
    monkeypatch.setattr(tb, "active_teams", lambda: {"lab"})
    _budget(monkeypatch, {})
    monkeypatch.setattr(te, "load", _load_ok)
    batches = _Batches()
    assert tb.submit(svc, _client(batches)) == 1
    assert (
        "trial_facts",
        {
            "extraction_status": "failed",
            "extraction_error": "Couldn't read the sources. Try again.",
        },
    ) in svc.updates


def test_one_failing_batch_doesnt_stop_collection(monkeypatch):
    svc = _Svc([_row("t1", "batched", batch="gone"), _row("t2", "batched", batch="ok")])

    class Flaky(_Batches):
        def retrieve(self, batch_id):
            if batch_id == "gone":
                raise RuntimeError("results expired")
            return super().retrieve(batch_id)

    from tests.test_trial_extract import VALID

    stored = []
    monkeypatch.setattr(te, "store", lambda _s, team, trial, *_a: stored.append(trial))
    assert tb.collect(svc, _client(Flaky([_succeeded("t2", _msg(VALID))]))) == 1
    assert stored == ["t2"]


def _succeeded(trial, msg):
    return SimpleNamespace(
        custom_id=tb.custom_id("lab", trial), result=SimpleNamespace(type="succeeded", message=msg)
    )


def _msg(answer_input):
    usage = SimpleNamespace(
        input_tokens=10000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=5000,
    )
    content = [SimpleNamespace(type="tool_use", name=te.TOOL, id="tu", input=answer_input)]
    return SimpleNamespace(
        stop_reason="end_turn", content=content, usage=usage, model="claude-opus-5-5"
    )


def test_collect_stores_results_at_half_price_and_retries_bad_ones(monkeypatch):
    from tests.test_trial_extract import VALID

    svc = _Svc(
        [
            _row("t1", "batched", attempts=1, batch="batch_1", sources=["s1", "s2"]),
            _row("t2", "batched", attempts=1, batch="batch_1"),
            _row("t3", "batched", attempts=2, batch="batch_1"),
        ]
    )
    bad = {**VALID, "arms": "none"}
    errored = SimpleNamespace(
        custom_id=tb.custom_id("lab", "t3"), result=SimpleNamespace(type="errored")
    )
    batches = _Batches([_succeeded("t1", _msg(VALID)), _succeeded("t2", _msg(bad)), errored])
    stored = []
    monkeypatch.setattr(
        te,
        "store",
        lambda _s, team, trial, r, m, usd, src, mode: stored.append((trial, usd, src, mode)),
    )
    assert tb.collect(svc, _client(batches)) == 1
    full = 10000 / 1e6 * 4 + 5000 / 1e6 * 20
    assert stored == [("t1", round(full / 2, 4), [{"id": "s1"}, {"id": "s2"}], "batch")]
    spend = [r for n, r in svc.inserts if n == "trial_extraction_spend"]
    assert [(r["trial_id"], r["mode"]) for r in spend] == [("t1", "batch"), ("t2", "batch")]
    statuses = [f.get("extraction_status") for n, f in svc.updates]
    assert statuses == ["queued", "failed"]  # t2 tries again; t3 is out of attempts


def test_collect_waits_for_a_running_batch_then_gives_up_when_stuck():
    svc = _Svc([_row("t1", "batched", attempts=1, batch="batch_1")])
    assert tb.collect(svc, _client(_Batches(status="in_progress"))) == 0
    assert svc.updates == []
    old = datetime.now(UTC) - timedelta(hours=31)
    tb.collect(svc, _client(_Batches(status="in_progress", created=old)))
    assert svc.updates[-1][1]["extraction_status"] == "queued"


def test_jats_refuses_entities_in_any_encoding():
    doc = (
        '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a [<!ENTITY x "y">]>'
        "<article><body><p>&x;</p></body></article>"
    ).encode("utf-16")
    with pytest.raises(jats.NotJats):
        jats.to_text(doc)
