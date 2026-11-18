"""Define the issue shared by discovery and both coverage researchers.

The neutral description fixes scope independently of publisher wording. Candidate
articles are feed hints; researchers still have to verify them in full text."""

from dataclasses import dataclass

from backend.sources.access import ArticleCandidate


@dataclass(frozen=True)
class ResearchIssue:
    """An issue the reader can select, together with the articles found for it."""

    label: str
    description: str
    candidates: tuple[ArticleCandidate, ...]
