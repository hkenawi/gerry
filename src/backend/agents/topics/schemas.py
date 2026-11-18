"""Define structured topic proposals returned by the topic discovery agent.

The application validates headline numbers against the search hits before it
creates topic choices for the reader."""

from enum import StrEnum
from dataclasses import dataclass
from pydantic import Field, BaseModel

MAX_TOPICS: int = 5


class IssueResolution(StrEnum):
    """Indicate whether to research now or invite the reader to refine the scope."""

    NARROW = "narrow"
    BROADEN = "broaden"
    READY = "ready"


@dataclass(frozen=True)
class TopicResolutionConstants:
    """Expose discovery routing vocabulary shared with the turn workflow."""

    resolutions: type[IssueResolution] = IssueResolution


TOPIC_RESOLUTION: TopicResolutionConstants = TopicResolutionConstants()


class ProposedTopic(BaseModel):
    """A neutral topic label and the numbers of the headlines it groups."""

    label: str = Field(min_length=3, max_length=90)
    description: str = Field(default="", max_length=320)
    headline_numbers: list[int] = Field(min_length=1)


class TopicProposal(BaseModel):
    """The discovery agent's proposed headline groups, at most five."""

    topics: list[ProposedTopic] = Field(default_factory=list, max_length=MAX_TOPICS)
    resolution: IssueResolution = TOPIC_RESOLUTION.resolutions.NARROW
