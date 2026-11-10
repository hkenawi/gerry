"""
Behavior tests for the structured research brief produced by the Lead agent.
"""

import pytest
from pydantic import ValidationError

from backend.agents.research_brief import ResearchBrief


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
