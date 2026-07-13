"""Is this URL safe for the server to fetch? (SSRF guard.)

``fetch_metadata`` makes the server issue an HTTP GET at a URL someone else chose.
That is a server-side request forgery sink: without a check, ``POST /resolve`` with
``http://169.254.169.254/latest/meta-data/`` reaches the cloud metadata service from
*inside* the network, and even when the body never comes back, connection-refused vs.
timeout tells an attacker which internal ports are open.

The rules used to live in ``atlas_mcp.lab``, which meant the MCP path was defended and
the HTTP API — five other ``fetch_metadata`` call sites — was not, against the same
sink. They live here so every caller shares them.

Two layers, because a URL check alone is not enough:

  * :func:`validate_public_url` — what the *caller submitted*: scheme, length, an
    obviously-internal hostname, a literal private IP, and a hostname that *resolves*
    to one (a public name pointing at internal infra).
  * :func:`open_public_url` — where the *fetch actually goes*. urllib follows
    redirects by default, so a validated public URL that 302s to 169.254.169.254
    sails through every pre-flight check. This re-runs the IP check on each hop.

Neither closes the DNS-rebinding window (the name could resolve differently between
the check and the connect). Airtight protection means checking at connect time —
pinning the socket to an already-validated IP — which stdlib urllib does not expose.
This raises the cost a great deal; it does not claim to be complete.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.request
from urllib.parse import urlsplit

MAX_URL_LEN = 2048

# http(s) only: file:// reads the disk, gopher:// and ftp:// have been used to smuggle
# arbitrary bytes into internal services.
ALLOWED_SCHEMES = ("http", "https")


class BlockedUrl(Exception):
    """The URL points somewhere the server must not fetch."""


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything not routable to on the public internet.

    ``not is_global`` replaces the old hand-listed set of categories, which kept missing
    ranges that are none of loopback/private/link-local/reserved yet still internal —
    notably CGNAT ``100.64.0.0/10``, where some clouds host their metadata endpoint.
    ``is_multicast`` and ``is_unspecified`` are added back explicitly: CPython reports
    ``is_global`` as *True* for multicast (it's globally-scoped in the registry sense),
    but you must never let the server emit to a multicast group, and ``0.0.0.0`` is a
    connect-to-self footgun.
    """
    return not ip.is_global or ip.is_multicast or ip.is_unspecified


def _check_host(host: str | None) -> None:
    """Reject a host that is internal by name, by literal IP, or by what it resolves to."""
    if not host:
        raise BlockedUrl("That URL has no host.")
    # A trailing dot makes a name fully-qualified without changing what it resolves to,
    # so "localhost." and "169.254.169.254." must be treated as "localhost"/the IP —
    # otherwise the name filter and the literal-IP parse both miss them and a resolver
    # that strips the dot at connect time reaches the internal target.
    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith((".localhost", ".internal")):
        raise BlockedUrl("That host isn't allowed.")

    # A literal IP never reaches DNS, so check it directly.
    try:
        literal = ipaddress.ip_address(lowered)
    except ValueError:
        literal = None
    if literal is not None:
        if is_blocked_ip(literal):
            raise BlockedUrl("That host isn't allowed.")
        return

    # A *public* name can still point at internal infra — the literal check can't see that.
    try:
        infos = socket.getaddrinfo(lowered, None)
    except OSError:
        return  # unresolvable: let the fetch surface the real error, don't guess
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if is_blocked_ip(ip):
            raise BlockedUrl("That host resolves to a disallowed address.")


def validate_public_url(url: str, *, resolve: bool = True) -> str:
    """The submitted URL, or raise :class:`BlockedUrl`.

    Guarantees the ONLY exception it raises is BlockedUrl — a malformed URL
    (``urlsplit`` raising ValueError) or an over-long DNS label (``getaddrinfo``
    raising UnicodeError) is a reason to reject, not to 500 the caller, which only
    catches BlockedUrl.

    ``resolve=False`` skips the DNS lookup and checks only what's in the string
    (scheme, length, literal IP, internal name). The API layer uses it for a fast,
    clean 400 on the obvious cases; the fetch layer keeps ``resolve=True`` so a public
    name pointing at an internal address is still caught (and each redirect re-checked)
    — that's the check that has to hold, and it avoids resolving the same host twice.
    """
    raw = (url or "").strip()
    if not raw:
        raise BlockedUrl("No URL given.")
    if len(raw) > MAX_URL_LEN:
        raise BlockedUrl("That URL is too long.")
    try:
        parts = urlsplit(raw)
        hostname = parts.hostname
    except ValueError as exc:  # malformed URL (bad IPv6 brackets, invalid host)
        raise BlockedUrl("That URL is malformed.") from exc
    if parts.scheme not in ALLOWED_SCHEMES:
        raise BlockedUrl("Only http(s) links can be fetched.")
    if not resolve:
        # Name/literal checks only — no getaddrinfo. Reuses _check_host by short-
        # circuiting the DNS step for a syntactically-internal host.
        _check_host_syntax(hostname)
        return raw
    try:
        _check_host(hostname)
    except UnicodeError as exc:  # getaddrinfo on a label >63 chars
        raise BlockedUrl("That host isn't a valid name.") from exc
    return raw


def _check_host_syntax(host: str | None) -> None:
    """The parts of _check_host that don't touch the network: empty, internal name,
    literal internal IP. Used by validate_public_url(resolve=False)."""
    if not host:
        raise BlockedUrl("That URL has no host.")
    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith((".localhost", ".internal")):
        raise BlockedUrl("That host isn't allowed.")
    try:
        literal = ipaddress.ip_address(lowered)
    except ValueError:
        return  # a name — the DNS check (skipped here) is what would vet it
    if is_blocked_ip(literal):
        raise BlockedUrl("That host isn't allowed.")


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-check every redirect target.

    Without this, the URL check above is decorative: an attacker serves a perfectly
    public https://evil.example/paper that 302s to http://169.254.169.254/, and urllib
    follows it silently. This is the hole that matters in practice — far more so than
    DNS rebinding, which needs a race.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)  # raises BlockedUrl -> the fetch fails, as it should
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_GuardedRedirectHandler)


def open_public_url(url: str, *, headers: dict[str, str], timeout: float):
    """Fetch `url` with every redirect hop re-validated. Raises :class:`BlockedUrl` if
    the target — or anywhere it redirects to — is not a public address."""
    validate_public_url(url)
    req = urllib.request.Request(url, headers=headers)
    return _opener.open(req, timeout=timeout)  # noqa: S310 — scheme + host validated above
