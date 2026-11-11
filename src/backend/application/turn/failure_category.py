"""
Typed failure categories and the reader-facing description of each.

Each category maps to one HTTP status and one plain-language message so that
handled failures never expose stack traces or credentials. Partial results,
such as a side with no usable articles, are not failures. They appear in the
answer and the tool-call records instead.
"""

from enum import StrEnum
from dataclasses import dataclass


class FailureCategory(StrEnum):
    """
    The kinds of failure the application distinguishes.
    """

    MODEL_UNAVAILABLE = "model_unavailable"
    RESEARCH_LIMIT_REACHED = "research_limit_reached"
    INVALID_OUTPUT = "invalid_output"
    PERSISTENCE_FAILURE = "persistence_failure"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class FailureDescription:
    """
    The HTTP status and reader-facing message of a category.
    """

    http_status: int
    message: str


FAILURE_DESCRIPTIONS: dict[FailureCategory, FailureDescription] = {
    FailureCategory.MODEL_UNAVAILABLE: FailureDescription(
        503, "The language model is unavailable right now. Please try again soon.",
    ),
    FailureCategory.RESEARCH_LIMIT_REACHED: FailureDescription(
        200, "We reached the research limit, so some gaps remain.",
    ),
    FailureCategory.INVALID_OUTPUT: FailureDescription(
        502, "We could not produce a valid answer. Please try again.",
    ),
    FailureCategory.PERSISTENCE_FAILURE: FailureDescription(
        503, "We could not save this conversation, so it may not continue later.",
    ),
    FailureCategory.UNEXPECTED: FailureDescription(
        500, "Something went wrong on our side. Please quote the request ID.",
    ),
}


def describe_failure(category: FailureCategory) -> FailureDescription:
    """
    Return the HTTP status and plain-language message for a failure category.
    """
    return FAILURE_DESCRIPTIONS[category]
