"""Discover candidate URLs from each outlet's current RSS or Atom feeds.

Feeds list only recent articles, so discovery is intended for recent news and does
not establish complete coverage. Every candidate still requires an independent
full article read and date check."""

import re
import xml.etree.ElementTree as ET

from urllib.parse import urljoin, urlsplit
from email.utils import parsedate_to_datetime
from datetime import date, datetime

from backend.sources.access import ArticleCandidate
from backend.sources.constants import SOURCE_CONSTANTS
from backend.sources.outlets import OutletConfiguration
from backend.sources.access.http import (
    FetchedDocument,
    SourceAccessError,
    validate_source_url,
)

FEED_SCOPE: str = "Searched current feed entries; completeness is unknown."


def _matches_query(title: str, snippet: str, query: str) -> bool:
    """Match event terms without requiring date words or generic comparison phrasing.

    A blank query matches every entry, for listing headlines in a period."""
    if not query.strip():
        return True
    if "|" in query:
        return any(
            _matches_query(title, snippet, variant)
            for variant in query.split("|")
            if variant.strip()
        )
    ignored: frozenset[str] = frozenset({
        "the", "and", "for", "with", "about", "coverage", "compare", "news",
        "event", "from", "between",
    })
    terms: set[str] = set(re.findall(r"[a-z]{3,}", query.lower())) - ignored
    available: set[str] = set(re.findall(r"[a-z]{3,}", f"{title} {snippet}".lower()))
    return bool(terms) and len(terms & available) / len(terms) >= 0.5


def parse_discovery_document(
    document: FetchedDocument,
    outlet: OutletConfiguration,
    query: str,
    start_date: date,
    end_date: date,
) -> tuple[ArticleCandidate, ...]:
    """Parse feed entries into restricted URL candidates."""
    candidates: list[ArticleCandidate] = []
    raw_entries: list[tuple[str, str, str, str | None]] = []
    has_declaration: bool = (
        b"<!DOCTYPE" in document.body.upper() or b"<!ENTITY" in document.body.upper()
    )
    if has_declaration:
        if "html" not in document.content_type.lower():
            raise SourceAccessError(
                SOURCE_CONSTANTS.access_statuses.EXTRACTION_FAILED,
                "Discovery XML contains an unsupported document declaration.",
            )
    root: ET.Element | None = None
    if not has_declaration:
        try:
            root = ET.fromstring(document.body)
        except ET.ParseError:
            root = None
    kind: str = root.tag.rsplit("}", 1)[-1] if root is not None else ""
    if root is None or kind not in ("rss", "feed"):
        raise SourceAccessError(
            SOURCE_CONSTANTS.access_statuses.EXTRACTION_FAILED,
            "Publisher did not return an RSS or Atom feed.",
        )
    entries: list[ET.Element] = root.findall(".//item") + root.findall("{*}entry")
    for entry in entries:
        title: str = entry.findtext("title") or entry.findtext("{*}title") or ""
        link: str = entry.findtext("link") or ""
        if not link:
            for atom_link in entry.findall("{*}link"):
                if atom_link.get("rel", "alternate") == "alternate":
                    link = atom_link.get("href", "")
                    break
        snippet: str = entry.findtext("description") or entry.findtext("{*}summary") or ""
        published: str | None = entry.findtext("pubDate") or entry.findtext("{*}published")
        raw_entries.append((link, title, snippet, published))
    seen: set[str] = set()
    for link, title, snippet, raw_date in raw_entries:
        if not link:
            continue
        try:
            url: str = validate_source_url(urljoin(document.url, link), outlet.article_hosts)
        except SourceAccessError:
            continue
        path: str = urlsplit(url).path
        if "/video/" in path or "/videos/" in path or url in seen:
            continue
        title = title or path.rsplit("/", 1)[-1].replace("-", " ")
        if not title or not _matches_query(title, snippet, query):
            continue
        publication: datetime | date | None = None
        if raw_date:
            try:
                try:
                    publication = (
                        date.fromisoformat(raw_date) if len(raw_date) == 10
                        else datetime.fromisoformat(raw_date)
                    )
                except ValueError:
                    publication = parsedate_to_datetime(raw_date)
                if isinstance(publication, datetime) and publication.utcoffset() is None:
                    continue
            except (ValueError, TypeError, OverflowError):
                continue
        day: date | None = publication.date() if isinstance(publication, datetime) else publication
        if day is not None and not start_date <= day <= end_date:
            continue
        seen.add(url)
        candidates.append(ArticleCandidate(
            outlet_id=outlet.outlet_id, url=url, title=title,
            snippet=re.sub(r"<[^>]*>", " ", snippet).strip() or None,
            published_at=publication,
        ))
    return tuple(candidates)
