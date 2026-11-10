"""
Typed failure categories and the reader-facing description of each.

Each category maps to one HTTP status and one plain-language message so that
handled failures never expose stack traces or credentials. Status values are a
draft for review with Person B and may be refined in the error-handling phase.
"""

from enum import StrEnum
from dataclasses import dataclass


class FailureCategory(StrEnum):
    """
    The kinds of failure the application distinguishes.
    """

    SOURCE_UNAVAILABLE = "source_unavailable"
    INCOMPLETE_TEXT = "incomplete_text"
    RESEARCHER_FAILURE = "researcher_failure"
    MODEL_UNAVAILABLE = "model_unavailable"
    RESEARCH_LIMIT_REACHED = "research_limit_reached"
    INVALID_OUTPUT = "invalid_output"
    PERSISTENCE_FAILURE = "persistence_failure"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class FailureDescription:
    """
    The HTTP status, reader-facing message, and retry eligibility of a category.
    """

    http_status: int
    message: str
    is_transient: bool


FAILURE_DESCRIPTIONS: dict[FailureCategory, FailureDescription] = {
    FailureCategory.SOURCE_UNAVAILABLE: FailureDescription(
        502, "We could not reach the news sources. Trying again may help.",
        True,
    ),
    FailureCategory.INCOMPLETE_TEXT: FailureDescription(
        200, "Some articles could not be read in full and were left out.",
        False,
    ),
    FailureCategory.RESEARCHER_FAILURE: FailureDescription(
        200, "One side's research did not finish, so this comparison is partial.",
        True,
    ),
    FailureCategory.MODEL_UNAVAILABLE: FailureDescription(
        503, "The language model is unavailable right now. Please try again soon.",
        True,
    ),
    FailureCategory.RESEARCH_LIMIT_REACHED: FailureDescription(
        200, "We reached the research limit, so some gaps remain.",
        False,
    ),
    FailureCategory.INVALID_OUTPUT: FailureDescription(
        502, "We could not produce a valid answer. Please try again.",
        True,
    ),
    FailureCategory.PERSISTENCE_FAILURE: FailureDescription(
        503, "We could not save this conversation, so it may not continue later.",
        False,
    ),
    FailureCategory.UNEXPECTED: FailureDescription(
        500, "Something went wrong on our side. Please quote the request ID.",
        False,
    ),
}


def describe_failure(category: FailureCategory) -> FailureDescription:
    """
    Return the HTTP status and plain-language message for a failure category.
    """
    return FAILURE_DESCRIPTIONS[category]
