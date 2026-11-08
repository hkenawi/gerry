"""
Structured findings a Researcher returns to the Lead after reading articles.

Every main focus must cite supporting passages so the Lead and Writer can trace
each classification back to the collected evidence.
"""

from enum import StrEnum

from pydantic import Field, BaseModel


class SourceGroup(StrEnum):
    """
    The two fixed outlet groups assigned by the project, never by the model.
    """

    LIBERAL = "liberal"
    CONSERVATIVE = "conservative"


class MainFocus(BaseModel):
    """
    One central aspect of an article, justified by supporting passages.
    """

    aspect: str
    article_id: str
    passage_ids: list[str] = Field(min_length=1)


class ResearcherFindings(BaseModel):
    """
    What one Researcher found for its assigned source group.
    """

    group: SourceGroup
    main_focuses: list[MainFocus]
    limitations: list[str]
