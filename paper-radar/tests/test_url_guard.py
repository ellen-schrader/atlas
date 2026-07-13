"""The SSRF guard in front of every server-side URL fetch."""

from __future__ import annotations

import urllib.error

import pytest

from paper_radar.ingest import url_guard
from paper_radar.ingest.url_guard import BlockedUrl, validate_public_url


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/abs/1706.03762",
        "http://www.nature.com/articles/x",
        "https://doi.org/10.1016/j.cell.2020.01.001",
    ],
)
def test_allows_public_http(monkeypatch, url):
    monkeypatch.setattr(
        url_guard.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )
    assert validate_public_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://host/x",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://localhost/x",
        "http://foo.localhost/x",
        "http://127.0.0.1/x",
        "https://10.0.0.5/a",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        "http://192.168.1.1/a",
        "http://[::1]/a",
        "http://0.0.0.0/a",
        "https://svc.internal/x",
        "https://x.example/" + "a" * 3000,  # over MAX_URL_LEN
    ],
)
def test_blocks_unsafe(url):
    with pytest.raises(BlockedUrl):
        validate_public_url(url)


def test_blocks_public_hostname_resolving_to_internal(monkeypatch):
    """The literal-IP check can't see this: the name is public, the address isn't."""
    monkeypatch.setattr(
        url_guard.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))]
    )
    with pytest.raises(BlockedUrl):
        validate_public_url("https://evil.example.com/paper")


def test_unresolvable_host_is_left_to_the_fetch(monkeypatch):
    """Not our job to decide DNS is broken — let the fetch surface the real error."""

    def boom(*_a, **_k):
        raise OSError("nxdomain")

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", boom)
    assert validate_public_url("https://does-not-exist.invalid/p")


def test_redirect_to_an_internal_address_is_blocked():
    """The hole a URL check alone cannot close, and the reason the guard sits at the
    fetch rather than at the caller.

    urllib follows redirects silently, so an attacker serves a perfectly public URL
    that 302s to the cloud metadata service and every pre-flight check passes. The
    guarded opener re-validates each hop, so the redirect is refused.
    """
    handler = url_guard._GuardedRedirectHandler()

    class _Resp:
        status = 302
        headers: dict[str, str] = {}

        def read(self):
            return b""

    req = urllib.request.Request("https://evil.example/paper")

    with pytest.raises(BlockedUrl):
        handler.redirect_request(
            req, _Resp(), 302, "Found", {}, "http://169.254.169.254/latest/meta-data/"
        )


def test_redirect_to_a_public_address_is_allowed(monkeypatch):
    """The guard must not break the redirects that make the resolver work at all —
    doi.org/10.x → the publisher is a redirect, and it's the happy path."""
    monkeypatch.setattr(
        url_guard.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )
    handler = url_guard._GuardedRedirectHandler()
    handler.parent = urllib.request.build_opener()  # HTTPRedirectHandler needs this

    class _Resp:
        status = 302
        headers: dict[str, str] = {}

        def read(self):
            return b""

    req = urllib.request.Request("https://doi.org/10.1016/j.cell.2020.01.001")
    new = handler.redirect_request(
        req, _Resp(), 302, "Found", {}, "https://www.cell.com/cell/fulltext/S0092-8674"
    )
    assert new is not None  # allowed through


def test_metadata_fetch_refuses_a_blocked_url(monkeypatch):
    """`_get` is the single fetch point for every lookup this codebase makes, so the
    guard holding there is what covers all five fetch_metadata call sites."""
    from paper_radar.ingest import metadata

    def _must_not_open(*_a, **_k):
        raise AssertionError("a blocked URL must never reach the socket")

    monkeypatch.setattr(url_guard._opener, "open", _must_not_open)
    # A blocked target is a failed fetch, not a crash — ingest never blocks on a bad link.
    assert metadata._get("http://169.254.169.254/latest/meta-data/") is None


def test_metadata_fetch_survives_a_network_error(monkeypatch):
    """The pre-existing contract: any fetch failure yields None, never an exception."""
    from paper_radar.ingest import metadata

    def _boom(*_a, **_k):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(url_guard._opener, "open", _boom)
    monkeypatch.setattr(
        url_guard.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )
    assert metadata._get("https://arxiv.org/abs/1706.03762") is None
