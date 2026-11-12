"""The projects router's own logic; RLS and closeness are in
test_projects_integration.py."""

from __future__ import annotations

from api import embeddings, projects


def test_no_description_no_embedding_call(monkeypatch):
    def boom(text, **k):
        raise AssertionError("should not embed")

    monkeypatch.setattr(embeddings, "embed_query", boom)
    assert projects._embed("user-1", "") is None


def test_a_failed_embedding_never_fails_the_save(monkeypatch):
    def down(text, **k):
        raise embeddings.EmbeddingError("Embeddings unavailable", status=503, detail="quota")

    monkeypatch.setattr(embeddings, "embed_query", down)
    assert projects._embed("user-2", "Tertiary lymphoid structures") is None


def test_the_description_is_embedded_as_a_query(monkeypatch):
    seen = []
    monkeypatch.setattr(embeddings, "embed_query", lambda text, **k: seen.append(text) or [0.1])
    assert projects._embed("user-3", "B cells in TLS") == [0.1]
    assert seen == ["B cells in TLS"]
