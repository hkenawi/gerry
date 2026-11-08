"""Extract publisher article text and metadata into immutable evidence snapshots.

Publisher-specific publication metadata takes precedence over extractor date
guesses. Missing or conflicting dates and visibly gated or short text are explicit
failures. Article content is retained as data and is never executed as instructions."""

import re
import trafilatura

from uuid import UUID, uuid4
from urllib.parse import urljoin
from datetime import UTC, datetime
from lxml.html import HtmlElement, HTMLParser, fromstring
from pydantic import JsonValue, TypeAdapter, ValidationError

from backend.sources.articles import ArticleRecord, ArticlePassage, PublicationDate
from backend.sources.constants import ArticleType, SOURCE_CONSTANTS, SourceMetadataField
from backend.sources.access.http import (
    SourceLimits,
    FetchedDocument,
    SourceAccessError,
    validate_source_url,
)


_JSON_ADAPTER: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_DATE_ADAPTER: TypeAdapter[PublicationDate] = TypeAdapter(PublicationDate)


def _find_article_nodes(value: JsonValue) -> list[dict[str, JsonValue]]:
    """Find article metadata in JSON-LD arrays and graphs, ignoring unrelated nodes."""
    fields: type[SourceMetadataField] = SOURCE_CONSTANTS.metadata
    if isinstance(value, list):
        return [node for item in value for node in _find_article_nodes(item)]
    if not isinstance(value, dict):
        return []
    kind: JsonValue = value.get(fields.TYPE.value)
    kinds: list[JsonValue] = kind if isinstance(kind, list) else [kind]
    nodes: list[dict[str, JsonValue]] = (
        [value] if any(item in SOURCE_CONSTANTS.article_schema_types for item in kinds)
        else []
    )
    return nodes + _find_article_nodes(value.get(fields.GRAPH.value))


def _select_metadata(tree: HtmlElement, url: str, title: str) -> dict[str, JsonValue]:
    """Select the primary article rather than dates from recommendation widgets."""
    nodes: list[dict[str, JsonValue]] = []
    script: HtmlElement
    for script in tree.xpath('//script[@type="application/ld+json"]'):
        try:
            nodes.extend(_find_article_nodes(_JSON_ADAPTER.validate_json(script.text or "")))
        except (ValidationError, RecursionError):
            continue
    fields: type[SourceMetadataField] = SOURCE_CONSTANTS.metadata
    for node in nodes:
        if node.get(fields.URL.value) == url or node.get(fields.HEADLINE.value) == title:
            return node
    if len(nodes) > 1:
        raise SourceAccessError(
            SOURCE_CONSTANTS.access_statuses.EXTRACTION_FAILED,
            "The primary article metadata could not be identified unambiguously.",
        )
    return nodes[0] if nodes else {}


def _parse_publisher_date(value: JsonValue) -> PublicationDate:
    """Parse only explicit publisher dates, preserving their precision and offset."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourceAccessError(
            SOURCE_CONSTANTS.access_statuses.DATE_CONFLICT,
            "Publisher date has an unsupported format.",
        )
    try:
        return _DATE_ADAPTER.validate_python(value)
    except ValidationError as error:
        raise SourceAccessError(
            SOURCE_CONSTANTS.access_statuses.DATE_CONFLICT,
            "Publisher date is invalid or its timezone is unknown.",
        ) from error


def extract_article(
    document: FetchedDocument,
    outlet_id: str,
    allowed_hosts: tuple[str, ...],
    limits: SourceLimits,
) -> ArticleRecord:
    """Build a dated snapshot only after extracting a substantive article body."""
    tree: HtmlElement = fromstring(
        document.body, parser=HTMLParser(no_network=True, huge_tree=False),
    )
    extracted = trafilatura.bare_extraction(
        document.body, include_comments=False, include_tables=False,
        favor_precision=True, with_metadata=True,
    )
    text: str = (extracted.text or "").strip() if extracted else ""
    title: str = (extracted.title or "").strip() if extracted else ""
    canonicals: list[str] = tree.xpath('//head/link[@rel="canonical"]/@href')
    canonical: str = validate_source_url(
        urljoin(document.url, canonicals[0]) if canonicals else document.url, allowed_hosts,
    )
    metadata: dict[str, JsonValue] = _select_metadata(tree, canonical, title)
    fields: type[SourceMetadataField] = SOURCE_CONSTANTS.metadata
    accessibility: JsonValue = metadata.get(fields.FREE_ACCESS.value)
    if accessibility is False or accessibility == "false":
        raise SourceAccessError(
            SOURCE_CONSTANTS.access_statuses.PAYWALL,
            "Publisher identifies the article as gated content.",
        )
    if len(text.split()) < limits.minimum_article_words:
        raise SourceAccessError(
            SOURCE_CONSTANTS.access_statuses.INCOMPLETE_TEXT,
            "Extracted text is too short to establish a usable article read.",
        )
    if not title:
        raise SourceAccessError(
            SOURCE_CONSTANTS.access_statuses.EXTRACTION_FAILED,
            "Article title could not be extracted.",
        )
    date_values: list[JsonValue] = [metadata.get(fields.PUBLISHED.value)]
    date_values.extend(tree.xpath(
        '//head/meta[@property="article:published_time" or @name="datePublished"]/@content',
    ))
    dates: list[PublicationDate] = [
        _parse_publisher_date(value) for value in date_values if value is not None
    ]
    if not dates:
        raise SourceAccessError(
            SOURCE_CONSTANTS.access_statuses.MISSING_DATE,
            "No explicit publisher publication date was found.",
        )
    calendar_dates: set[PublicationDate] = {
        value.date() if isinstance(value, datetime) else value for value in dates
    }
    if len(calendar_dates) != 1:
        raise SourceAccessError(
            SOURCE_CONSTANTS.access_statuses.DATE_CONFLICT,
            "Publisher publication dates disagree.",
        )
    author_value: JsonValue = metadata.get(fields.AUTHOR.value)
    authors: list[JsonValue] = author_value if isinstance(author_value, list) else [author_value]
    publisher_bylines: list[str] = []
    for author in authors:
        name: JsonValue = author.get(fields.NAME.value) if isinstance(author, dict) else author
        if isinstance(name, str) and name.strip():
            publisher_bylines.append(name.strip())
    bylines: tuple[str, ...] = tuple(dict.fromkeys(publisher_bylines)) or tuple(
        part.strip() for part in (extracted.author or "").split(";") if part.strip()
    )
    credits: str = " ".join(bylines)
    origin: str | None = None
    if re.search(r"Associated Press", credits, re.IGNORECASE) or "(AP)" in text[:250]:
        origin = "AP"
    elif re.search(r"\bReuters\b", credits, re.IGNORECASE) or "(Reuters)" in text[:250]:
        origin = "Reuters"
    elif re.search(r"Agence France-Presse", credits, re.IGNORECASE) or "(AFP)" in text[:250]:
        origin = "AFP"
    kind: str = str(metadata.get(fields.TYPE.value, ""))
    section: str = " ".join(tree.xpath('//head/meta[@property="article:section"]/@content')).lower()
    article_type: ArticleType = SOURCE_CONSTANTS.article_types.UNKNOWN
    if "opinion" in section or "Opinion" in kind:
        article_type = SOURCE_CONSTANTS.article_types.OPINION
    elif "analysis" in section or "Analysis" in kind:
        article_type = SOURCE_CONSTANTS.article_types.ANALYSIS
    elif "NewsArticle" in kind:
        article_type = SOURCE_CONSTANTS.article_types.REPORTING
    article_id: UUID = uuid4()
    paragraphs: list[str] = [line.strip() for line in text.splitlines() if line.strip()]
    return ArticleRecord(
        article_id=article_id,
        outlet_id=outlet_id,
        requested_url=document.url,
        canonical_url=canonical,
        title=title,
        bylines=bylines,
        published_at=dates[0],
        updated_at=_parse_publisher_date(metadata.get(fields.UPDATED.value)),
        retrieved_at=datetime.now(UTC),
        article_type=article_type,
        reporting_origin=origin,
        syndicated=True if origin is not None else None,
        passages=tuple(
            ArticlePassage(passage_id=f"{article_id}:p{index:04d}", text=paragraph)
            for index, paragraph in enumerate(paragraphs, start=1)
        ),
    )
