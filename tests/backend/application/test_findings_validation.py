"""
Behavior tests for validating Researcher findings against saved evidence.

Python, not the model, decides whether a cited article or passage really exists
for the conversation and belongs to the Researcher's assigned group.
"""

import pytest

from backend.agents.researcher_findings import ResearcherFindings, SourceGroup
from backend.application.findings_validation import (
    InvalidFindings,
    validate_findings,
)


def build_findings(group: SourceGroup, article_id: str, passage_id: str):
    """
    Build findings that cite one passage of one article.
    """
    return ResearcherFindings.model_validate(
        {
            "group": group,
            "article_ids": [article_id],
            "main_focuses": [
                {
                    "aspect": "Police response",
                    "article_id": article_id,
                    "passage_ids": [passage_id],
                }
            ],
            "limitations": [],
        }
    )


def test_findings_citing_real_saved_articles_of_their_group_are_accepted(
    make_article,
) -> None:
    """
    A cited article that was saved for the same group passes validation.
    """
    article = make_article("npr")
    findings = build_findings(
        SourceGroup.LIBERAL,
        str(article.article_id),
        article.passages[0].passage_id,
    )

    validate_findings(findings, (article,))


def test_findings_citing_an_unsaved_article_are_rejected(make_article) -> None:
    """
    An article ID that was never read is an invented citation.
    """
    saved = make_article("npr")
    invented = make_article("nbc")
    findings = build_findings(
        SourceGroup.LIBERAL,
        str(invented.article_id),
        invented.passages[0].passage_id,
    )

    with pytest.raises(InvalidFindings):
        validate_findings(findings, (saved,))


def test_findings_citing_the_other_groups_article_are_rejected(
    make_article,
) -> None:
    """
    A liberal Researcher may not cite an article from a conservative outlet.
    """
    conservative_article = make_article("fox")
    findings = build_findings(
        SourceGroup.LIBERAL,
        str(conservative_article.article_id),
        conservative_article.passages[0].passage_id,
    )

    with pytest.raises(InvalidFindings):
        validate_findings(findings, (conservative_article,))


def test_findings_citing_a_passage_not_in_the_cited_article_are_rejected(
    make_article,
) -> None:
    """
    The passage must belong to the article the focus names.
    """
    first = make_article("npr")
    second = make_article("nbc")
    findings = build_findings(
        SourceGroup.LIBERAL,
        str(first.article_id),
        second.passages[0].passage_id,
    )

    with pytest.raises(InvalidFindings):
        validate_findings(findings, (first, second))
