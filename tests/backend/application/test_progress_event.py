"""
Behavior tests for progress events and their Server-Sent Events encoding.
"""

import json

import pytest
from pydantic import ValidationError

from backend.application.progress_event import ProgressEvent, format_sse_frame


def test_event_encodes_as_a_well_formed_sse_frame() -> None:
    """
    A frame has an event line, a JSON data line, and a blank-line terminator.
    """
    event = ProgressEvent(
        type="agent_started",
        agent="researcher_liberal",
        message="Getting our sources in a row.",
        timestamp="2026-11-08T12:00:00Z",
    )

    frame = format_sse_frame(event)

    lines = frame.split("\n")
    assert lines[0] == "event: agent_started"
    assert lines[1].startswith("data: ")
    assert json.loads(lines[1].removeprefix("data: "))["agent"] == "researcher_liberal"
    assert frame.endswith("\n\n")


def test_event_rejects_unknown_type() -> None:
    """
    Only the defined progress event types may be published.
    """
    with pytest.raises(ValidationError):
        ProgressEvent(
            type="made_up",
            agent="lead",
            message="x",
            timestamp="2026-11-08T12:00:00Z",
        )
