"""
Structured research brief that the Lead agent produces from a reader's request.

The brief is the contract between clarification and research: research only
starts from a brief whose status is clear and whose publication window is known.
"""

from enum import StrEnum
from datetime import date

from pydantic import BaseModel, model_validator


class BriefStatus(StrEnum):
    """
    Whether the Lead can start research or must ask the reader a question.
    """

    CLEAR = "clear"
    NEEDS_CLARIFICATION = "needs_clarification"


class ResearchBrief(BaseModel):
    """
    The event to research and the publication window articles must fall within.
    """

    status: BriefStatus
    event: str
    start_date: date | None = None
    end_date: date | None = None
    clarifying_question: str | None = None

    @model_validator(mode="after")
    def validate_period_and_question(self) -> "ResearchBrief":
        """
        Require a valid window for clear briefs and a question otherwise.
        """
        if self.status is BriefStatus.CLEAR:
            if self.start_date is None or self.end_date is None:
                raise ValueError("A clear brief requires start_date and end_date.")
            if self.end_date < self.start_date:
                raise ValueError("end_date must not be before start_date.")
        elif not self.clarifying_question:
            raise ValueError("A brief needing clarification requires a question.")
        return self
