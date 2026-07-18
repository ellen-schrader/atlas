"""URL cleaning and dedup-key normalization.

Kept apart from ``pdf_extract`` on purpose: these are pure string helpers, but
``pdf_extract`` imports PyMuPDF (AGPL-3.0-or-commercial) at module level. The
API and the MCP server need only the helpers, so importing them from here keeps
PyMuPDF — and its licence — out of everything but the Teams-PDF importer.
"""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

# Trailing characters that are almost never part of the real URL.
_TRAILING_JUNK = ".,);:]}>”’'\""

# Hosts that are never a paper — skip before doing a (slow) metadata lookup.
# Shared by the Teams-PDF importer and the live channel ingest path.
_SKIP_HOSTS = (
    "x.com",
    "twitter.com",
    "github.com",
    "huggingface.co",
    "linkedin.com",
    "youtube.com",
    "youtu.be",
    "teams.cloud.microsoft",
    "teams.microsoft.com",
)

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


# A DOI on its own, optionally behind the "doi:" handle prefix people copy from
# citation lines. Suffixes may contain slashes (legacy Wiley/SICI), so \S+ is right.
# [0-9] rather than \d so it matches the ASCII-only client regex — Python's \d also
# accepts non-ASCII digit scripts, which would coerce inputs the browser rejects.
_BARE_DOI_RE = re.compile(r"^(?:doi:\s*)?(10\.[0-9]{4,9}/\S+)$", re.IGNORECASE)

# A scheme-less input is only turned into an https URL when it starts with something
# shaped like a real web host: dot-separated labels ending in an alphabetic TLD. This
# is deliberately strict — a bare or oddly-encoded IP (``2130706433``, ``0x7f000001``,
# ``127.1``, ``localhost``) must NOT gain a scheme here, or it would sail past the
# API's fast syntactic SSRF gate (which can't parse those as IPs) and rely solely on
# the deferred fetch-time DNS check. Denying coercion keeps their original hard 400.
_HOSTLIKE_PREFIX_RE = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:[:/?#]|$)", re.IGNORECASE)


def coerce_fetch_url(raw: str) -> str:
    """Turn what people actually paste into something the http(s)-only guard accepts.

    The add-paper box invites "arXiv, DOI, PubMed, bioRxiv, or a publisher page",
    and people oblige: a bare ``10.1038/...``, a ``doi:`` prefix, or a scheme-less
    ``arxiv.org/abs/...``. None of those is a fetchable URL, so without this they
    all die at ``validate_public_url`` with "Only http(s) links can be fetched."
    A bare DOI becomes its doi.org resolver URL; a scheme-less *host-shaped* input
    gets ``https://``. Inputs that already carry a scheme pass through untouched, and
    anything that doesn't look like a DOI or a hostname is left alone so the guard
    still rejects it. This widens what is accepted, never what is fetched — the SSRF
    guard runs on the result, and coercing only host-shaped strings keeps encoded
    internal addresses (bare/hex/short IPs) from bypassing its fast syntactic check.
    """
    raw = raw.strip()
    m = _BARE_DOI_RE.match(raw)
    if m:
        return f"https://doi.org/{m.group(1)}"
    try:
        scheme = urlsplit(raw).scheme
    except ValueError:
        # Malformed (e.g. bad IPv6 brackets): hand it through so validate_public_url
        # turns it into its clean "That URL is malformed." rejection.
        return raw
    if raw and not scheme and _HOSTLIKE_PREFIX_RE.match(raw):
        return f"https://{raw}"
    return raw


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


def is_skip_host(url: str) -> bool:
    """True for a URL whose host is never a paper (social/code/Teams itself)."""
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    return any(h in host for h in _SKIP_HOSTS)


# URLs in freeform message text: http(s) up to whitespace/quote/angle-bracket.
# A trailing ')' or '.' from surrounding prose is trimmed by _clean_url.
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
# A link pasted into Teams becomes <a href="URL">Title</a>, so the URL lives in
# the href — capture it before tag-stripping would discard it.
_HREF_RE = re.compile(r"""href\s*=\s*["']?(https?://[^"'>\s]+)""", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
# A bare DOI typed without a URL, e.g. "10.1016/j.cell.2026.06.027" (optionally
# prefixed "doi:"). The registrant is 4–9 digits per the DOI spec, which rules
# out version strings like "10.2.3"; a trailing sentence '.' is trimmed later.
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)


def _unwrap_safelink(url: str) -> str:
    """Outlook SafeLinks wrap the real URL in a ``?url=`` param — return the target."""
    parts = urlsplit(url)
    if parts.netloc.lower().endswith("safelinks.protection.outlook.com"):
        target = parse_qs(parts.query).get("url", [None])[0]
        if target:
            return target
    return url


def extract_urls_from_text(text: str | None) -> list[str]:
    """Every http(s) URL in a blob of text, cleaned and de-duped in order.

    Teams sends a pasted link as an HTML anchor whose visible text is the page
    title, so the URL is only in the ``href`` — those are pulled out first, then
    the visible text (with tags stripped) is scanned for bare or markdown-style
    links. A bare DOI typed on its own (no URL) is recognized too and returned as
    a ``https://doi.org/…`` link. Unescapes entities and unwraps Outlook
    SafeLinks. The live channel-ingest counterpart to ``extract_urls_from_dir``.
    """
    if not text:
        return []
    text = html.unescape(text)
    stripped = _TAG_RE.sub(" ", text)
    candidates = _HREF_RE.findall(text) + _URL_RE.findall(stripped)
    # Bare DOIs, scanned in text with URLs removed so a DOI inside a URL path
    # isn't pulled out again (the full URL is already a candidate).
    candidates += ["https://doi.org/" + doi for doi in _DOI_RE.findall(_URL_RE.sub(" ", stripped))]
    seen: set[str] = set()
    out: list[str] = []
    for match in candidates:
        url = _clean_url(_unwrap_safelink(_clean_url(match)))
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out
