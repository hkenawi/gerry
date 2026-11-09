"""
Collect reader-visible tool-call records for one request.

Every agent and tool wrapper appends here so the final response can show all
sub-agent activity, including failed calls, in the order it happened.
"""

from collections.abc import Callable

from backend.application.tool_call_record import ToolCallOutcome, ToolCallRecord


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
