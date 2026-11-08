"""Expose source results for discovery and article-reading tool boundaries.

These contracts distinguish discovered candidates from collected evidence and
preserve per-outlet failures without performing external requests."""

from backend.sources.access.contracts import (
    ArticleCandidate,
    ArticleReadResult,
    ArticleSearchResult,
    SourceAccessOutcome,
)

__all__: list[str] = [
    "ArticleCandidate",
    "ArticleReadResult",
    "ArticleSearchResult",
    "SourceAccessOutcome",
]
