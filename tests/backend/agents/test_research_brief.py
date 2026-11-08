"""
Behavior tests for the structured research brief produced by the Lead agent.
"""

import pytest
from pydantic import ValidationError

from backend.agents.research_brief import ResearchBrief


def test_clear_brief_with_event_and_period_is_valid() -> None:
    """
    A clear brief names the event and a bounded publication window.
    """
    brief = ResearchBrief.model_validate(
        {
            "status": "clear",
            "event": "Protests in France over pension reform",
            "start_date": "2026-11-01",
            "end_date": "2026-11-07",
        }
    )

    assert brief.status == "clear"
    assert brief.start_date.isoformat() == "2026-11-01"


def test_brief_rejects_end_date_before_start_date() -> None:
    """
    An inverted window would silently exclude every article.
    """
    with pytest.raises(ValidationError):
        ResearchBrief.model_validate(
            {
                "status": "clear",
                "event": "Protests in France",
                "start_date": "2026-11-07",
                "end_date": "2026-11-01",
            }
        )


def test_clear_brief_without_period_is_rejected() -> None:
    """
    Research must not launch until the event window is known.
    """
    with pytest.raises(ValidationError):
        ResearchBrief.model_validate(
            {"status": "clear", "event": "Protests in France"}
        )


def test_needs_clarification_brief_carries_a_question_and_no_period() -> None:
    """
    An unclear request yields a clarifying question instead of a period.
    """
    brief = ResearchBrief.model_validate(
        {
            "status": "needs_clarification",
            "event": "the protests",
            "clarifying_question": "Which protests, and roughly when?",
        }
    )

    assert brief.clarifying_question == "Which protests, and roughly when?"
