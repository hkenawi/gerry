"""
Structured output of the Writer agent.

The Writer returns claims that each cite supporting passage IDs. It does not
produce the final Markdown; application code renders and validates the answer so
citations and layout stay consistent.
"""

from pydantic import Field, BaseModel


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

    summary: list[Claim] = Field(min_length=1)
    overlap: list[Claim] = Field(default_factory=list)
    differences: list[Claim] = Field(default_factory=list)
