"""
Structured findings a Researcher returns to the Lead after reading articles.

Every main focus must cite supporting passages so the Lead and Writer can trace
each classification back to the collected evidence.
"""

from enum import StrEnum
from typing import Self

from pydantic import Field, BaseModel, model_validator


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


class AttributedAccount(BaseModel):
    """Keep one reported account tied to its speaker and supporting passages."""

    account: str = Field(min_length=1)
    attributed_to: str = Field(min_length=1)
    article_id: str = Field(min_length=1)
    passage_ids: list[str] = Field(min_length=1)


class ResearcherFindings(BaseModel):
    """
    What one Researcher found for its assigned source group.
    """

    group: SourceGroup
    main_focuses: list[MainFocus]
    limitations: list[str]
    article_ids: list[str]
    accounts: list[AttributedAccount] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_read_inventory(self) -> Self:
        """Require every cited article to belong to the explicit read inventory."""
        inventory: set[str] = set(self.article_ids)
        if len(inventory) != len(self.article_ids):
            raise ValueError("Read inventory must contain distinct article IDs.")
        references: list[MainFocus | AttributedAccount] = [
            *self.main_focuses, *self.accounts,
        ]
        if any(reference.article_id not in inventory for reference in references):
            raise ValueError("Cited articles must belong to the read inventory.")
        return self
