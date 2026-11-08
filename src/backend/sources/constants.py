"""Define typed values shared by source records and their consumers.

The constants object scopes source-specific enums and validation settings so
article and access contracts agree without depending on agent runtime code."""

from enum import StrEnum
from typing import ClassVar
from pydantic import ConfigDict
from dataclasses import dataclass

from backend.agents.researcher_findings import SourceGroup


class ArticleType(StrEnum):
    """Identify the publisher's content category without inferring political views."""

    REPORTING = "reporting"
    ANALYSIS = "analysis"
    OPINION = "opinion"
    UNKNOWN = "unknown"


class SourceAccessStatus(StrEnum):
    """Describe an observed source outcome without inferring missing coverage."""

    SUCCESS = "success"
    NO_RESULTS = "no_results"
    PAYWALL = "paywall"
    ACCESS_DENIED = "access_denied"
    MISSING_DATE = "missing_date"
    DATE_CONFLICT = "date_conflict"
    OUTSIDE_WINDOW = "outside_window"
    INCOMPLETE_TEXT = "incomplete_text"
    FETCH_FAILED = "fetch_failed"
    EXTRACTION_FAILED = "extraction_failed"
    STORAGE_FAILED = "storage_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class SourceMetadataField(StrEnum):
    """Name publisher metadata fields interpreted by the extraction boundary."""

    TYPE = "@type"
    GRAPH = "@graph"
    URL = "url"
    HEADLINE = "headline"
    PUBLISHED = "datePublished"
    UPDATED = "dateModified"
    AUTHOR = "author"
    NAME = "name"
    FREE_ACCESS = "isAccessibleForFree"


class OutletIdentifier(StrEnum):
    """Keep roster keys shared by discovery strategies and configuration in sync."""

    NPR = "npr"
    NBC = "nbc"
    HUFFPOST = "huffpost"
    ABC = "abc"
    CBS = "cbs"
    FOX = "fox"
    DAILY_CALLER = "dailycaller"
    BREITBART = "breitbart"
    NEW_YORK_POST = "nypost"
    EXAMINER = "examiner"


@dataclass(frozen=True)
class SourceConstants:
    """Expose source vocabulary and immutable-record validation settings."""

    article_types: type[ArticleType] = ArticleType
    access_statuses: type[SourceAccessStatus] = SourceAccessStatus
    groups: type[SourceGroup] = SourceGroup
    metadata: type[SourceMetadataField] = SourceMetadataField
    outlet_ids: type[OutletIdentifier] = OutletIdentifier
    article_schema_types: tuple[str, ...] = (
        "NewsArticle", "Article", "ReportageNewsArticle", "AnalysisNewsArticle",
        "OpinionNewsArticle",
    )
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


SOURCE_CONSTANTS: SourceConstants = SourceConstants()
