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


@dataclass(frozen=True)
class SourceConstants:
    """Expose source vocabulary and immutable-record validation settings."""

    article_types: type[ArticleType] = ArticleType
    access_statuses: type[SourceAccessStatus] = SourceAccessStatus
    groups: type[SourceGroup] = SourceGroup
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


SOURCE_CONSTANTS: SourceConstants = SourceConstants()
