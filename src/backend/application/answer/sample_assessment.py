"""
Assess the collected sample and decide how the final answer may be framed.

The decision is made in code from article counts. Articles are never trimmed to
balance the two sides; unequal counts are stated and only a side with no
usable articles switches the answer to an objective summary.
"""

from enum import StrEnum
from dataclasses import dataclass

from backend.sources.articles import ArticleRecord
from backend.sources.constants import ArticleType
from backend.agents.researcher_findings import SourceGroup

MINIMUM_ARTICLES_PER_GROUP: int = 2
MINIMUM_OUTLETS_PER_GROUP: int = 2


class AnswerMode(StrEnum):
    """
    How the Writer is allowed to frame the answer.
    """

    COMPARISON = "comparison"
    SUMMARY_ONLY = "summary_only"
    NO_EVIDENCE = "no_evidence"


@dataclass(frozen=True)
class SampleAssessment:
    """
    The answer mode, the reason for it, and a plain statement of the counts.
    """

    mode: AnswerMode
    reason: str
    sample_statement: str
    thin_groups: tuple[SourceGroup, ...]


def count_outlets(articles: tuple[ArticleRecord, ...]) -> int:
    """
    Count the distinct outlets represented in a set of articles.
    """
    return len({article.outlet_id for article in articles})


def describe_group_sample(
    group: SourceGroup,
    articles: tuple[ArticleRecord, ...],
) -> str:
    """
    State one side's article and outlet counts in plain words.
    """
    article_word: str = "article" if len(articles) == 1 else "articles"
    outlet_word: str = "outlet" if count_outlets(articles) == 1 else "outlets"
    return (
        f"{len(articles)} {group.value} {article_word} "
        f"from {count_outlets(articles)} {outlet_word}"
    )


def meets_floor(articles: tuple[ArticleRecord, ...]) -> bool:
    """
    Check the floor using reporting articles only.
    """
    reporting: tuple[ArticleRecord, ...] = tuple(
        article
        for article in articles
        if article.article_type is ArticleType.REPORTING
    )
    return (
        len(reporting) >= MINIMUM_ARTICLES_PER_GROUP
        and count_outlets(reporting) >= MINIMUM_OUTLETS_PER_GROUP
    )


def assess_sample(
    articles_by_group: dict[SourceGroup, tuple[ArticleRecord, ...]],
) -> SampleAssessment:
    """
    Decide the answer mode and describe the sample for the reader.
    """
    liberal: tuple[ArticleRecord, ...] = articles_by_group[SourceGroup.LIBERAL]
    conservative: tuple[ArticleRecord, ...] = articles_by_group[
        SourceGroup.CONSERVATIVE
    ]
    statement: str = (
        f"{describe_group_sample(SourceGroup.LIBERAL, liberal)} and "
        f"{describe_group_sample(SourceGroup.CONSERVATIVE, conservative)}"
    )
    if not liberal and not conservative:
        return SampleAssessment(
            AnswerMode.NO_EVIDENCE,
            "No articles could be retrieved from either side.",
            statement,
            (),
        )
    for group, articles in articles_by_group.items():
        if not articles:
            return SampleAssessment(
                AnswerMode.SUMMARY_ONLY,
                (
                    f"No {group.value} articles could be retrieved, so there is "
                    "nothing to compare against. This is an objective summary "
                    "of the available coverage only."
                ),
                statement,
                (),
            )
    thin: tuple[SourceGroup, ...] = tuple(
        group
        for group, articles in articles_by_group.items()
        if not meets_floor(articles)
    )
    return SampleAssessment(AnswerMode.COMPARISON, "", statement, thin)
