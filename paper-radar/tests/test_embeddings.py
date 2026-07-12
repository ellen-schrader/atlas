"""Offline tests for the Voyage embedding client (stubbed HTTP, no network)."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from api import embeddings
from api.config import ApiSettings


def _settings(**overrides) -> ApiSettings:
    kwargs = {"voyage_api_key": "test-key", "embedding_dim": 3}
    kwargs.update(overrides)
    return ApiSettings(_env_file=None, **kwargs)


class _FakeResponse(io.BytesIO):
    """urlopen returns a context manager whose body json.load can read."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _voyage_body(vectors: list[list[float]], *, shuffle: bool = False) -> bytes:
    data = [{"index": i, "embedding": v} for i, v in enumerate(vectors)]
    if shuffle:
        data = list(reversed(data))
    return json.dumps({"data": data}).encode()


def test_embed_texts_batches_and_orders_by_index(monkeypatch):
    requests: list[dict] = []

    def fake_urlopen(request, timeout=None):
        payload = json.loads(request.data)
        requests.append(payload)
        n = len(payload["input"])
        base = len(requests) * 10.0
        # Return rows out of order to prove we sort by `index`.
        return _FakeResponse(_voyage_body([[base + i, 0, 0] for i in range(n)], shuffle=True))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(embeddings, "BATCH_SIZE", 2)

    vectors = embeddings.embed_texts(["a", "b", "c"], settings=_settings())

    assert [payload["input"] for payload in requests] == [["a", "b"], ["c"]]
    assert all(payload["input_type"] == "document" for payload in requests)
    assert all(payload["model"] == "voyage-4" for payload in requests)
    # Batch 1 → 10.0/11.0 in text order, batch 2 → 20.0.
    assert [v[0] for v in vectors] == [10.0, 11.0, 20.0]


def test_embed_query_uses_query_input_type(monkeypatch):
    seen: list[str] = []

    def fake_urlopen(request, timeout=None):
        payload = json.loads(request.data)
        seen.append(payload["input_type"])
        return _FakeResponse(_voyage_body([[1.0, 0, 0]]))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert embeddings.embed_query("myeloid cells", settings=_settings()) == [1.0, 0, 0]
    assert seen == ["query"]


def test_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(embeddings.VOYAGE_URL, 429, "rate limited", None, None)
        return _FakeResponse(_voyage_body([[1.0, 0, 0]]))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(embeddings.time, "sleep", lambda _s: None)

    assert embeddings.embed_texts(["a"], settings=_settings()) == [[1.0, 0, 0]]
    assert calls["n"] == 2


def test_non_retryable_http_error_raises(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(embeddings.VOYAGE_URL, 401, "bad key", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(embeddings.EmbeddingError, match="401"):
        embeddings.embed_texts(["a"], settings=_settings())


def test_missing_key_raises():
    with pytest.raises(embeddings.EmbeddingError, match="VOYAGE_API_KEY"):
        embeddings.embed_texts(["a"], settings=_settings(voyage_api_key=""))


def test_unknown_provider_raises():
    with pytest.raises(embeddings.EmbeddingError, match="provider"):
        embeddings.embed_texts(["a"], settings=_settings(embedding_provider="local"))


def test_dimension_mismatch_raises(monkeypatch):
    def fake_urlopen(request, timeout=None):
        return _FakeResponse(_voyage_body([[1.0, 2.0]]))  # 2-dim, settings expect 3

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(embeddings.EmbeddingError, match="dim"):
        embeddings.embed_texts(["a"], settings=_settings())


def test_empty_input_makes_no_requests(monkeypatch):
    def fake_urlopen(request, timeout=None):  # pragma: no cover — must not run
        raise AssertionError("no request expected")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert embeddings.embed_texts([], settings=_settings()) == []


def test_paper_text_joins_title_and_abstract():
    assert embeddings.paper_text("Title", "Abstract") == "Title\n\nAbstract"
    assert embeddings.paper_text("Title", None) == "Title"
    assert embeddings.paper_text(None, "Abstract") == "Abstract"
    assert embeddings.paper_text(None, None) == ""
    assert embeddings.paper_text("  ", "\n") == ""
