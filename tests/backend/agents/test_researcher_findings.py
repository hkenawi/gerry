"""
Behavior tests for the structured findings a Researcher returns to the Lead.

Passage references are plain string IDs here; resolving them against saved
articles is the source-storage component's responsibility.
"""

import pytest
from pydantic import ValidationError

from backend.agents.researcher_findings import ResearcherFindings


def build_findings(**overrides: object) -> dict[str, object]:
    """
    Build a valid findings payload, allowing individual fields to be replaced.
    """
    payload: dict[str, object] = {
        "group": "liberal",
        "article_ids": ["npr-1"],
        "main_focuses": [
            {
                "aspect": "Police response",
                "article_id": "npr-1",
                "passage_ids": ["npr-1-p3"],
            }
        ],
        "limitations": [],
    }
    payload.update(overrides)
    return payload


def test_focus_without_supporting_passage_is_rejected() -> None:
    """
    A classification with no supporting passage is not evidence-based.
    """
    unsupported = [
        {"aspect": "Police response", "article_id": "npr-1", "passage_ids": []}
    ]

    with pytest.raises(ValidationError):
        ResearcherFindings.model_validate(build_findings(main_focuses=unsupported))


def test_findings_preserve_attributed_accounts_and_read_article_inventory() -> None:
    """Retain the evidence the Lead needs to compare conflicting accounts."""
    findings: ResearcherFindings = ResearcherFindings.model_validate(
        build_findings(
            article_ids=["npr-1"],
            accounts=[
                {
                    "account": "Officials reported six injuries.",
                    "attributed_to": "Local emergency officials",
                    "article_id": "npr-1",
                    "passage_ids": ["npr-1-p3"],
                },
            ],
        ),
    )

    assert findings.article_ids == ["npr-1"]
    assert findings.accounts[0].attributed_to == "Local emergency officials"


def test_findings_cannot_cite_an_article_outside_the_read_inventory() -> None:
    """Keep claims tied to the articles the Researcher reports having read."""
    with pytest.raises(ValidationError):
        ResearcherFindings.model_validate(build_findings(article_ids=["fox-1"]))
