"""Expose the saved article and passage records used across backend components.

Retrieval and storage implementations can change behind these validated evidence
records without requiring callers to import implementation modules."""

from backend.sources.articles.contracts import (
    ArticleRecord,
    ArticlePassage,
    PublicationDate,
)

__all__: list[str] = ["ArticleRecord", "ArticlePassage", "PublicationDate"]
