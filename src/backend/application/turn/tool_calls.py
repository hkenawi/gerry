"""Record tool activity during a chat turn.

The HTTP response includes these records, and the recorder can notify a
listener when a tool finishes so the progress stream can report it."""

from enum import StrEnum
from pydantic import BaseModel
from collections.abc import Callable


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


class ToolCallRecorder:
    """
    Append-only log of the tool calls made while handling one request.
    """

    def __init__(self, on_record: Callable[[ToolCallRecord], None] | None = None) -> None:
        """
        Start with no recorded calls.
        """
        self._records: list[ToolCallRecord] = []
        self._on_record: Callable[[ToolCallRecord], None] | None = on_record

    @property
    def records(self) -> tuple[ToolCallRecord, ...]:
        """
        Return the calls recorded so far, oldest first.
        """
        return tuple(self._records)

    def record(
        self,
        agent: str,
        tool: str,
        outcome: ToolCallOutcome,
        error: str | None = None,
    ) -> None:
        """
        Append one call attributed to the agent that made it.
        """
        record: ToolCallRecord = ToolCallRecord(
            agent=agent, tool=tool, outcome=outcome, error=error,
        )
        self._records.append(record)
        if self._on_record is not None:
            self._on_record(record)
