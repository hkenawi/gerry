"""
Reader-visible record of a single tool call made by any agent.

Records are returned in the ``tool_calls`` field of the chat response so that
sub-agent activity, including failed calls, can be inspected.
"""

from enum import StrEnum

from pydantic import BaseModel


class ToolCallOutcome(StrEnum):
    """
    Whether a tool call completed or failed.
    """

    SUCCESS = "success"
    FAILURE = "failure"


class ToolCallRecord(BaseModel):
    """
    One tool invocation, attributed to the agent that made it.
    """

    agent: str
    tool: str
    outcome: ToolCallOutcome
    error: str | None = None
