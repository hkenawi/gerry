"""
Behavior tests for failure categories and their reader-facing responses.
"""

import pytest

from backend.application.failure_category import (
    FailureCategory,
    describe_failure,
)


@pytest.mark.parametrize("category", list(FailureCategory))
def test_every_category_has_a_plain_language_description(
    category: FailureCategory,
) -> None:
    """
    No failure may reach a reader without a status and a readable message.
    """
    description = describe_failure(category)

    assert 400 <= description.http_status <= 599 or description.http_status == 200
    assert description.message.strip() != ""


@pytest.mark.parametrize("category", list(FailureCategory))
def test_messages_never_expose_internals(category: FailureCategory) -> None:
    """
    Reader-facing text must not leak stack traces or credentials.
    """
    message = describe_failure(category).message.lower()

    for forbidden in ("traceback", "api_key", "secret", "exception"):
        assert forbidden not in message


def test_known_categories_map_to_agreed_statuses() -> None:
    """
    Persistence outages are 503, bad model output is 502, unknowns are 500.
    """
    assert describe_failure(FailureCategory.PERSISTENCE_FAILURE).http_status == 503
    assert describe_failure(FailureCategory.INVALID_OUTPUT).http_status == 502
    assert describe_failure(FailureCategory.UNEXPECTED).http_status == 500


@pytest.mark.parametrize(
    "category",
    [
        FailureCategory.SOURCE_UNAVAILABLE,
        FailureCategory.MODEL_UNAVAILABLE,
        FailureCategory.INVALID_OUTPUT,
        FailureCategory.RESEARCHER_FAILURE,
    ],
)
def test_temporary_failures_are_marked_transient(
    category: FailureCategory,
) -> None:
    """
    Failures that may succeed on another attempt are eligible for bounded retry.
    """
    assert describe_failure(category).is_transient is True


@pytest.mark.parametrize(
    "category",
    [
        FailureCategory.INCOMPLETE_TEXT,
        FailureCategory.RESEARCH_LIMIT_REACHED,
        FailureCategory.PERSISTENCE_FAILURE,
        FailureCategory.UNEXPECTED,
    ],
)
def test_other_failures_are_not_retried(category: FailureCategory) -> None:
    """
    Retrying cannot fix these, so they must never be retried automatically.
    """
    assert describe_failure(category).is_transient is False
