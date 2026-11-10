"""
Behavior tests for validating Researcher findings against saved evidence.

The tests check that cited evidence exists in the conversation and belongs to
the group assigned by the application, even when the model names another group."""

import pytest

from backend.agents.researcher_findings import ResearcherFindings, SourceGroup
from backend.application.evidence.findings_validation import (
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
    """Accept assigned evidence even if the model names a different group."""
    article = make_article("npr")
    findings = build_findings(
        SourceGroup.CONSERVATIVE,
        str(article.article_id),
        article.passages[0].passage_id,
    )

    validate_findings(findings, (article,), assigned_group=SourceGroup.LIBERAL)


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
        validate_findings(findings, (saved,), assigned_group=SourceGroup.LIBERAL)


def test_findings_citing_the_other_groups_article_are_rejected(
    make_article,
) -> None:
    """Reject another group's article even if its group matches the model label."""
    conservative_article = make_article("fox")
    findings = build_findings(
        SourceGroup.CONSERVATIVE,
        str(conservative_article.article_id),
        conservative_article.passages[0].passage_id,
    )

    with pytest.raises(InvalidFindings):
        validate_findings(
            findings,
            (conservative_article,),
            assigned_group=SourceGroup.LIBERAL,
        )


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
        validate_findings(findings, (first, second), assigned_group=SourceGroup.LIBERAL)
