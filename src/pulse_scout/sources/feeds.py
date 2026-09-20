"""Turning RSS and Atom bodies into items.

Parsed with the standard library. `feedparser` would be the obvious dependency, but this
project already decided that configuration costs no dependency, and the same argument holds
here: ElementTree handles both formats, and what a real feed actually breaks on is never the
XML grammar — it is the encoding, the BOM, and servers lying about the content type.

Three defences, each earned by a real observation:

* **Sniff the body, never the header.** Several verified sources report `text/html` and return
  valid XML. The reverse also happens: a 200 with an HTML error page. Only the body is true.
* **Tolerate a BOM.** The Azure release feed — 200 entries, one of the highest-value tier 1
  sources — sends a UTF-8 BOM before the XML declaration, which makes a strict parser refuse
  the whole document. Verified 2026-09-20.
* **Match by local tag name.** RSS feeds mix in `dc:`, `content:`, `media:` and `atom:`
  namespaces at will. Matching fully-qualified names means a feed breaks the moment it adds a
  namespace it did not have yesterday.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from pulse_scout.models import Item

# Summaries only ever feed ranking, a prompt or a card. Keeping the whole article body would
# bloat the database and, more importantly, retain more third-party text than we need.
MAX_SUMMARY_CHARS = 800

_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


class FeedError(ValueError):
    """The body is not a feed we can read. Always reported, never silently skipped."""


def local_name(tag: str) -> str:
    """`{http://www.w3.org/2005/Atom}entry` -> `entry`."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def sniff(body: bytes) -> str:
    """What this body actually is: 'xml', 'json', 'html' or 'unknown'."""
    head = body.lstrip(b"\xef\xbb\xbf").lstrip()[:400].lower()
    if not head:
        return "unknown"
    if head.startswith(b"<?xml") or head.startswith(b"<rss") or head.startswith(b"<feed"):
        return "xml"
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return "html"
    if head.startswith((b"{", b"[")):
        return "json"
    # An XML document may open with a comment or a stylesheet instruction.
    if head.startswith(b"<"):
        return "html" if b"<html" in head else "xml"
    return "unknown"


def clean_text(raw: str | None) -> str:
    """Feed descriptions are HTML fragments. Reduce them to plain text."""
    if not raw:
        return ""
    text = html.unescape(_TAG.sub(" ", raw))
    text = _WHITESPACE.sub(" ", text).strip()
    if len(text) > MAX_SUMMARY_CHARS:
        text = text[:MAX_SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"
    return text


def parse_timestamp(raw: str | None) -> datetime | None:
    """RFC 822 (RSS) or ISO 8601 (Atom), always returned as aware UTC.

    An unparseable date returns None rather than `now()`. Pretending an undated item is fresh
    would hand it the full recency bonus it has not earned.
    """
    if not raw or not raw.strip():
        return None
    value = raw.strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _children(element: ElementTree.Element) -> dict[str, list[ElementTree.Element]]:
    found: dict[str, list[ElementTree.Element]] = {}
    for child in element:
        found.setdefault(local_name(child.tag), []).append(child)
    return found


def _first_text(children: dict[str, list[ElementTree.Element]], *names: str) -> str | None:
    for name in names:
        for element in children.get(name, []):
            if element.text and element.text.strip():
                return element.text
    return None


def _atom_link(children: dict[str, list[ElementTree.Element]]) -> str | None:
    """Atom puts the URL in an attribute, and a feed may carry several links per entry."""
    links = children.get("link", [])
    for element in links:
        if element.get("rel", "alternate") == "alternate" and element.get("href"):
            return element.get("href")
    for element in links:
        if element.get("href"):
            return element.get("href")
    # RSS style: the URL is the element's text.
    return _first_text(children, "link")


def _root(body: bytes) -> ElementTree.Element:
    kind = sniff(body)
    if kind == "html":
        raise FeedError("server returned an HTML page, not a feed")
    if kind == "json":
        raise FeedError("body is JSON, not a feed — is this source configured with the wrong kind?")
    if kind == "unknown":
        raise FeedError("body is empty or unrecognisable")
    stripped = body.lstrip(b"\xef\xbb\xbf").lstrip()
    try:
        return ElementTree.fromstring(stripped)
    except ElementTree.ParseError as exc:
        raise FeedError(f"malformed XML: {exc}") from exc


def parse_feed(body: bytes, *, source_name: str, tier: int) -> list[Item]:
    """All items in an RSS or Atom body, in feed order.

    A document that is not a feed raises. An individual entry that is unusable (no title) is
    skipped — one broken entry should not cost the other 199.
    """
    root = _root(body)
    root_name = local_name(root.tag)

    if root_name == "feed":
        entries = [child for child in root if local_name(child.tag) == "entry"]
    elif root_name == "rss":
        channels = [child for child in root if local_name(child.tag) == "channel"]
        entries = [
            item
            for channel in channels
            for item in channel
            if local_name(item.tag) == "item"
        ]
    elif root_name == "RDF":
        # RSS 1.0 puts items next to the channel rather than inside it.
        entries = [child for child in root if local_name(child.tag) == "item"]
    else:
        raise FeedError(f"unexpected root element <{root_name}> — not RSS or Atom")

    items: list[Item] = []
    for entry in entries:
        children = _children(entry)
        title = _first_text(children, "title")
        if not title or not title.strip():
            continue
        summary = _first_text(children, "summary", "description", "content", "encoded")
        published = parse_timestamp(
            _first_text(children, "published", "pubDate", "updated", "date")
        )
        items.append(
            Item.create(
                source_name=source_name,
                tier=tier,
                title=clean_text(title),
                url=_atom_link(children),
                summary=clean_text(summary),
                published_at=published,
                raw_id=_first_text(children, "id", "guid"),
            )
        )
    return items
