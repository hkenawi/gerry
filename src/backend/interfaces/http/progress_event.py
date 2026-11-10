"""
Progress events published while a turn runs, and their SSE text encoding.

The chat progress route uses these events to report work as it happens over
Server-Sent Events, independently of the final chat response."""

from enum import StrEnum
from datetime import datetime

from pydantic import BaseModel


class ProgressEventType(StrEnum):
    """
    The kinds of real activity that can be reported to the reader.
    """

    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"


class ProgressEvent(BaseModel):
    """
    One report of work in progress, attributed to an agent.
    """

    type: ProgressEventType
    agent: str
    message: str
    timestamp: datetime


def format_sse_frame(event: ProgressEvent) -> str:
    """
    Encode a progress event as one Server-Sent Events frame.
    """
    return f"event: {event.type.value}\ndata: {event.model_dump_json()}\n\n"
