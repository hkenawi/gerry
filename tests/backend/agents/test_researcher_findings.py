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


def test_findings_with_supported_focus_are_valid() -> None:
    """
    A main focus backed by at least one passage reference is accepted.
    """
    findings = ResearcherFindings.model_validate(build_findings())

    assert findings.group == "liberal"
    assert findings.main_focuses[0].passage_ids == ["npr-1-p3"]


def test_focus_without_supporting_passage_is_rejected() -> None:
    """
    A classification with no supporting passage is not evidence-based.
    """
    unsupported = [
        {"aspect": "Police response", "article_id": "npr-1", "passage_ids": []}
    ]

    with pytest.raises(ValidationError):
        ResearcherFindings.model_validate(build_findings(main_focuses=unsupported))


def test_group_must_be_liberal_or_conservative() -> None:
    """
    Source groups are fixed by the project, so other group names are invalid.
    """
    with pytest.raises(ValidationError):
        ResearcherFindings.model_validate(build_findings(group="centrist"))
