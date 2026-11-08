"""
Behavior tests for the tool-call record shown to readers in ``tool_calls``.

Records must make sub-agent activity visible, including failed calls.
"""

import pytest
from pydantic import ValidationError

from backend.application.tool_call_record import ToolCallRecord


def test_failed_call_is_representable_with_error_message() -> None:
    """
    A failed tool call is preserved with its outcome and a plain-language error.
    """
    record = ToolCallRecord.model_validate(
        {
            "agent": "researcher_liberal",
            "tool": "read_article",
            "outcome": "failure",
            "error": "The article could not be retrieved.",
        }
    )

    assert record.outcome == "failure"
    assert record.error == "The article could not be retrieved."


def test_record_without_agent_is_rejected() -> None:
    """
    Every record must identify which agent made the call.
    """
    with pytest.raises(ValidationError):
        ToolCallRecord.model_validate({"tool": "read_article", "outcome": "success"})
