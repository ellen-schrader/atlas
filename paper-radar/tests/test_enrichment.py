"""Offline tests for batch tagging (no Anthropic calls)."""

from __future__ import annotations

import types

import pytest
from pydantic import BaseModel, ValidationError

from api import enrichment
from api.enrichment import MAX_TAGS, enrich_batch


class _Model(BaseModel):
    papers: list[dict]


def _settings(**kw):
    base = {"anthropic_api_key": "sk-ant-test", "anthropic_model": "claude-sonnet-5"}
    return types.SimpleNamespace(**{**base, **kw})


def _papers(n: int, start: int = 0) -> list[dict]:
    return [
        {"id": f"p{i}", "title": f"Paper {i}", "abstract": f"Abstract {i}"}
        for i in range(start, start + n)
    ]


def _truncation_error() -> ValidationError:
    """The error a reply cut off mid-JSON actually raises."""
    try:
        _Model.model_validate_json('{"papers":[{"id":"p0","tags":["spatial-')
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


class _FakeClient:
    """Stands in for anthropic.Anthropic; records each call's size and max_tokens."""

    def __init__(self, on_call):
        self.messages = types.SimpleNamespace(parse=on_call)


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Install a fake `anthropic` module; return the list that records calls."""
    calls: list[dict] = []
    holder: dict = {}

    def parse(*, model, max_tokens, messages, output_format):
        ids = [
            line.split("id=")[1].split(">")[0]
            for line in messages[0]["content"].splitlines()
            if line.startswith("<paper id=")
        ]
        calls.append({"ids": ids, "max_tokens": max_tokens})
        return holder["responder"](ids)

    monkeypatch.setitem(
        __import__("sys").modules,
        "anthropic",
        types.SimpleNamespace(Anthropic=lambda api_key: _FakeClient(parse)),
    )
    return types.SimpleNamespace(calls=calls, holder=holder)


def _ok(ids, tags=("alpha", "beta", "gamma")):
    papers = [types.SimpleNamespace(id=i, tags=list(tags)) for i in ids]
    return types.SimpleNamespace(parsed_output=types.SimpleNamespace(papers=papers))


# --- the token budget --------------------------------------------------------


def test_max_tokens_scales_with_the_batch(fake_anthropic):
    fake_anthropic.holder["responder"] = _ok
    enrich_batch(_papers(15), settings=_settings())
    # 15 papers must not be asked for inside the old fixed 2000-token cap.
    assert fake_anthropic.calls[0]["max_tokens"] == 3000


def test_max_tokens_has_a_floor_for_tiny_batches(fake_anthropic):
    fake_anthropic.holder["responder"] = _ok
    enrich_batch(_papers(1), settings=_settings())
    assert fake_anthropic.calls[0]["max_tokens"] == 1024


# --- retrying a truncated reply ---------------------------------------------


def test_truncated_reply_is_retried_in_halves(fake_anthropic):
    # The whole batch used to be discarded on one truncation. Now the same papers
    # go back in two smaller calls, which is what actually fits.
    err = _truncation_error()

    def responder(ids):
        if len(ids) > 2:
            raise err
        return _ok(ids)

    fake_anthropic.holder["responder"] = responder
    out = enrich_batch(_papers(8), settings=_settings())

    assert set(out) == {f"p{i}" for i in range(8)}
    sizes = [len(c["ids"]) for c in fake_anthropic.calls]
    assert sizes == [8, 4, 2, 2, 4, 2, 2]  # 8 fails, each half fails, quarters succeed


def test_half_that_still_fails_does_not_sink_the_other_half(fake_anthropic):
    # Splitting must be per-branch: one unrecoverable paper costs only itself.
    err = _truncation_error()

    def responder(ids):
        if "p0" in ids:
            raise err
        return _ok(ids)

    fake_anthropic.holder["responder"] = responder
    out = enrich_batch(_papers(4), settings=_settings())
    assert set(out) == {"p1", "p2", "p3"}


def test_single_paper_that_will_not_parse_is_given_up_on(fake_anthropic):
    # The recursion has to bottom out rather than split forever.
    err = _truncation_error()
    fake_anthropic.holder["responder"] = lambda ids: (_ for _ in ()).throw(err)
    assert enrich_batch(_papers(1), settings=_settings()) == {}
    assert len(fake_anthropic.calls) == 1


def test_non_parse_errors_are_not_retried(fake_anthropic):
    # A 401 is not going to parse better in two calls; splitting would just
    # multiply a guaranteed failure across the batch.
    def responder(ids):
        raise RuntimeError("401 invalid x-api-key")

    fake_anthropic.holder["responder"] = responder
    assert enrich_batch(_papers(8), settings=_settings()) == {}
    assert len(fake_anthropic.calls) == 1


# --- tags --------------------------------------------------------------------


def test_tags_are_normalized_and_capped(fake_anthropic):
    fake_anthropic.holder["responder"] = lambda ids: _ok(
        ids, tags=("  Spatial-Omics ", "", "B", "c", "d", "e", "f", "g")
    )
    out = enrich_batch(_papers(1), settings=_settings())
    assert out["p0"][0] == "spatial-omics"  # trimmed and lowercased
    assert "" not in out["p0"]  # blanks dropped
    assert len(out["p0"]) == MAX_TAGS  # 7 non-blank tags trimmed to 6


# --- the early exits ---------------------------------------------------------


def test_no_api_key_is_a_no_op():
    assert enrich_batch(_papers(3), settings=_settings(anthropic_api_key="")) == {}


def test_papers_without_title_or_abstract_are_skipped(fake_anthropic):
    fake_anthropic.holder["responder"] = _ok
    items = _papers(1) + [{"id": "empty", "title": None, "abstract": "   "}]
    out = enrich_batch(items, settings=_settings())
    assert set(out) == {"p0"}
    assert fake_anthropic.calls[0]["ids"] == ["p0"]


def test_nothing_usable_makes_no_call(fake_anthropic):
    fake_anthropic.holder["responder"] = _ok
    assert enrich_batch([{"id": "x", "title": "", "abstract": None}], settings=_settings()) == {}
    assert fake_anthropic.calls == []


def test_batch_size_default_is_what_the_backfill_uses():
    assert enrichment.BATCH_SIZE == 15
