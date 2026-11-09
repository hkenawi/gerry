"""
Structured output of the Lead agent: the research brief and aspect alignment.

The alignment compares, for each aspect, how each group's sampled coverage
treated it. It states central focus, incidental mention, or absence from the
sampled articles, and never infers motives or claims concealment.
"""

from enum import StrEnum

from pydantic import Field, BaseModel, model_validator

from backend.agents.research_brief import ResearchBrief


class CoverageState(StrEnum):
    """
    How prominently a group's sampled articles treated one aspect.
    """

    CENTRAL = "central_focus"
    INCIDENTAL = "incidental_mention"
    NOT_IN_SAMPLE = "not_in_sample"


class AspectTreatment(BaseModel):
    """
    One group's treatment of an aspect, backed by supporting passages.
    """

    state: CoverageState
    note: str = ""
    passage_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_evidence_unless_absent(self) -> "AspectTreatment":
        """
        Require supporting passages whenever coverage is said to exist.
        """
        if self.state is not CoverageState.NOT_IN_SAMPLE and not self.passage_ids:
            raise ValueError("Coverage that exists must cite supporting passages.")
        return self


class AspectAlignment(BaseModel):
    """
    One aspect compared across the liberal and conservative samples.
    """

    aspect: str = Field(min_length=1)
    liberal: AspectTreatment
    conservative: AspectTreatment


class LeadOutcome(BaseModel):
    """
    The Lead's final output: a brief, plus an alignment once research is done.
    """

    brief: ResearchBrief
    alignment: list[AspectAlignment] = Field(default_factory=list)
