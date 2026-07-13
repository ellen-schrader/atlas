"""URL cleaning and dedup-key normalization.

Kept apart from ``pdf_extract`` on purpose: these are pure string helpers, but
``pdf_extract`` imports PyMuPDF (AGPL-3.0-or-commercial) at module level. The
API and the MCP server need only the helpers, so importing them from here keeps
PyMuPDF — and its licence — out of everything but the Teams-PDF importer.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Trailing characters that are almost never part of the real URL.
_TRAILING_JUNK = ".,);:]}>”’'\""

# Query params that are pure tracking/analytics noise: dropping them (plus any
# "utm_*") lets the same paper shared with and without a tracker dedupe to one.
# Meaningful params such as ``id`` (openreview) are deliberately kept.
_TRACKING_PARAMS = {
    "ct",
    "af",
    "dgcid",
    "via",
    "cid",
    "ref",
    "ref_src",
    "spm",
    "fbclid",
    "gclid",
    "mibextid",
    "sr_share",
    "rss",
}


def _clean_url(url: str) -> str:
    """Trim whitespace and trailing punctuation from a candidate URL."""
    url = url.strip()
    while url and url[-1] in _TRAILING_JUNK:
        url = url[:-1]
    return url


def _normalize_key(url: str) -> str:
    """Key used only for dedup (never stored).

    Lowercases the host and drops a leading ``www.``, removes the fragment and
    any trailing slash, and strips tracking query params (``utm_*`` and the
    denylist above) while keeping meaningful ones. Remaining params are sorted so
    order does not matter.
    """
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    # Some Teams exports percent-encode the '=' in query strings (e.g. via%3Dihub).
    raw_query = parts.query.replace("%3D", "=").replace("%3d", "=")
    kept = [
        (k, v)
        for k, v in parse_qsl(raw_query, keep_blank_values=False)
        if not (k.lower().startswith("utm_") or k.lower() in _TRACKING_PARAMS)
    ]
    kept.sort()
    path = parts.path.rstrip("/")
    return urlunsplit(("", host, path, urlencode(kept), ""))
