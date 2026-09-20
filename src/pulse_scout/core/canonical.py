"""Turning a feed's idea of a URL into one stable identity per story.

This is load-bearing rather than cosmetic. Most of the configured sources are *snapshots*,
not streams: the Azure feed returns its newest 200 entries on every call, CISA returns its
whole catalogue, HuggingFace returns the same 50 models. Without a stable key the pipeline
would re-ingest the same items every single day. The key is what makes "have I seen this
before?" answerable, so anything that makes two URLs for the same story look different —
a tracking parameter, a trailing slash, an AMP host — has to be removed here.

Conservative on purpose: it only strips things that provably do not change what is served.
Merging two genuinely different pages would silently delete a story from the digest, which is
a much worse failure than keeping a duplicate that the clustering step catches anyway.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Parameters that identify the *referrer*, never the content.
_TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "__hs", "hsa_", "vero_", "mkt_")
_TRACKING_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "referrer",
        "at_medium",
        "at_campaign",
        "cmpid",
        "sh",
        "s",  # x.com / twitter share id
    }
)

_DEFAULT_PORTS = {"http": "80", "https": "443"}

# Hosts that only ever mirror another page of the same site.
_HOST_PREFIXES = ("www.", "m.", "amp.", "mobile.")


def _is_tracking(key: str) -> bool:
    lowered = key.lower()
    return lowered in _TRACKING_KEYS or lowered.startswith(_TRACKING_PREFIXES)


def canonical_url(url: str | None) -> str | None:
    """One stable spelling of a URL, or None if it is not a usable http(s) address."""
    if not url:
        return None
    candidate = url.strip()
    if not candidate:
        return None

    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return None
    if not parts.hostname:
        return None

    host = parts.hostname.lower()
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix) and len(host) > len(prefix) + 3:
            host = host[len(prefix) :]
            break

    netloc = host
    port = parts.port
    if port is not None and str(port) != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"

    path = parts.path or "/"
    # Google's and Reddit's AMP wrappers append /amp to the real path.
    if path.endswith("/amp"):
        path = path[: -len("/amp")]
    elif path.endswith("/amp/"):
        path = path[: -len("/amp/")]
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(key, value) for key, value in pairs if not _is_tracking(key)]
    # Sorted so that ?a=1&b=2 and ?b=2&a=1 are the same story.
    query = urlencode(sorted(kept))

    # Fragments are client-side; no feed uses them to select content.
    return urlunsplit((scheme, netloc, path, query, ""))


def item_key(*, source_name: str, url: str | None, raw_id: str | None, title: str) -> str:
    """The identity of one item, stable across days.

    Preference order matters: the canonical URL is shared between sources and therefore also
    collapses the same story arriving twice, while a feed's own guid is only unique within
    that feed. The title fallback is last and weakest — it is there so that an item without
    either still gets a key instead of being dropped.
    """
    canonical = canonical_url(url)
    if canonical:
        return canonical
    if raw_id and raw_id.strip():
        digest = hashlib.sha1(f"{source_name}|{raw_id.strip()}".encode()).hexdigest()
        return f"guid:{digest}"
    # Collapse internal whitespace too: feeds pad and wrap titles inconsistently, and
    # "A   Title" and "A Title" are the same story on two different days.
    normalised = " ".join(title.split()).casefold()
    digest = hashlib.sha1(f"{source_name}|{normalised}".encode()).hexdigest()
    return f"title:{digest}"
