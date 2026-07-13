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
    """Anything not routable on the public internet: loopback, RFC1918, link-local
    (which is where 169.254.169.254 lives), reserved, and 0.0.0.0."""
    return bool(
        ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_unspecified
    )


def _check_host(host: str | None) -> None:
    """Reject a host that is internal by name, by literal IP, or by what it resolves to."""
    if not host:
        raise BlockedUrl("That URL has no host.")
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith((".localhost", ".internal")):
        raise BlockedUrl("That host isn't allowed.")

    # A literal IP never reaches DNS, so check it directly.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if is_blocked_ip(literal):
            raise BlockedUrl("That host isn't allowed.")
        return

    # A *public* name can still point at internal infra — the literal check can't see that.
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return  # unresolvable: let the fetch surface the real error, don't guess
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if is_blocked_ip(ip):
            raise BlockedUrl("That host resolves to a disallowed address.")


def validate_public_url(url: str) -> str:
    """The submitted URL, or raise :class:`BlockedUrl`. Call before fetching."""
    raw = (url or "").strip()
    if not raw:
        raise BlockedUrl("No URL given.")
    if len(raw) > MAX_URL_LEN:
        raise BlockedUrl("That URL is too long.")
    parts = urlsplit(raw)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise BlockedUrl("Only http(s) links can be fetched.")
    _check_host(parts.hostname)
    return raw


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
