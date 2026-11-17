"""
Structured outputs of the topic-scout agents.

The planner turns a reader's request into a headline search. The clusterer groups
numbered headlines into a few neutral topics. Code validates both outputs, so a
topic can only ever point at headlines that were really found.
"""

from datetime import date

from pydantic import Field, BaseModel

MAX_TOPICS: int = 5


class TopicSearch(BaseModel):
    """
    The headline search implied by the reader's request.
    """

    topic: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class ProposedTopic(BaseModel):
    """
    One neutral topic label and the numbers of the headlines it groups.
    """

    label: str = Field(min_length=3, max_length=90)
    headline_numbers: list[int] = Field(min_length=1)


class TopicProposal(BaseModel):
    """
    The clusterer's proposed topics, at most five.
    """

    topics: list[ProposedTopic] = Field(default_factory=list, max_length=MAX_TOPICS)
