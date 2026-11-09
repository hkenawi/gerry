"""
Validate Researcher findings against the evidence actually saved.

A Researcher may only cite articles that were read and saved for the current
conversation, that belong to its assigned group, and passages that belong to the
cited article. This is checked in code rather than trusted to the prompt.
"""

from backend.sources.articles import ArticleRecord
from backend.application.outlet_assignments import group_for_outlet
from backend.agents.researcher_findings import (
    MainFocus,
    ResearcherFindings,
    AttributedAccount,
)


class InvalidFindings(ValueError):
    """
    Raised when findings cite evidence that was not saved for their group.
    """


def validate_findings(
    findings: ResearcherFindings,
    saved_articles: tuple[ArticleRecord, ...],
) -> None:
    """
    Reject findings that cite unsaved articles, other groups, or foreign passages.
    """
    saved: dict[str, ArticleRecord] = {
        str(article.article_id): article for article in saved_articles
    }
    for article_id in findings.article_ids:
        article: ArticleRecord | None = saved.get(article_id)
        if article is None:
            raise InvalidFindings("Findings cite an article that was never saved.")
        if group_for_outlet(article.outlet_id) is not findings.group:
            raise InvalidFindings("Findings cite an article from the other group.")
    references: list[MainFocus | AttributedAccount] = [
        *findings.main_focuses,
        *findings.accounts,
    ]
    for reference in references:
        passage_ids: set[str] = {
            passage.passage_id for passage in saved[reference.article_id].passages
        }
        if not set(reference.passage_ids) <= passage_ids:
            raise InvalidFindings("Findings cite a passage outside the cited article.")
