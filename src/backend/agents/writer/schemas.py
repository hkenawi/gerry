"""
Structured output of the Writer agent.

The Writer returns claims that each cite supporting passage IDs. It does not
produce the final Markdown; application code renders and validates the answer so
citations and layout stay consistent.
"""

from typing import Self
from pydantic import Field, BaseModel, model_validator


class Claim(BaseModel):
    """
    One statement of fact or comparison with its supporting passages.
    """

    text: str = Field(min_length=1)
    passage_ids: list[str] = Field(min_length=1)


class WriterReport(BaseModel):
    """
    The Writer's findings: a summary, shared ground, and differences.
    """

    summary: list[Claim] = Field(default_factory=list)
    overlap: list[Claim] = Field(default_factory=list)
    differences: list[Claim] = Field(default_factory=list)
    evidence_gap: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_summary_or_gap(self) -> Self:
        """Require a cited summary or a specific request for missing evidence."""
        if not self.summary and not (self.evidence_gap or "").strip():
            raise ValueError("Provide a cited summary or a specific evidence gap.")
        return self
