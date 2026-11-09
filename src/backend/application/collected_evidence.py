"""
Gather the saved articles each source group's Researchers reported reading.

Both the Writer tool and the turn orchestration need the same view of the
evidence, so it lives here rather than in either of them.
"""

from backend.sources.articles import ArticleRecord
from backend.application.request_state import RequestState
from backend.agents.researcher_findings import SourceGroup


def collect_articles_by_group(
    state: RequestState,
) -> dict[SourceGroup, tuple[ArticleRecord, ...]]:
    """
    Return, per group, the saved articles named in that group's findings.
    """
    saved: dict[str, ArticleRecord] = {
        str(article.article_id): article
        for article in state.store.list_articles(state.conversation_id)
    }
    return {
        group: tuple(
            saved[article_id]
            for article_id in dict.fromkeys(
                article_id
                for findings in state.findings[group]
                for article_id in findings.article_ids
            )
            if article_id in saved
        )
        for group in SourceGroup
    }
