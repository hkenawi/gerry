"""Verify the failure metadata shared by the turn workflow and HTTP boundary.

The public lookup supplies reader-facing text and transport status codes.
These checks cover the mapping once for all declared categories."""

from backend.application.turn.failure_category import (
    FailureCategory,
    FailureDescription,
    describe_failure,
)


def test_failure_descriptions_have_reader_safe_messages_and_valid_statuses() -> None:
    """Require a usable description for every category the app can report."""
    category: FailureCategory
    for category in FailureCategory:
        description: FailureDescription = describe_failure(category)
        assert 400 <= description.http_status <= 599 or description.http_status == 200
        assert description.message.strip(), category
        assert not any(
            term in description.message.lower()
            for term in ("traceback", "api_key", "secret", "exception")
        ), category


def test_failure_metadata_preserves_status_and_transience() -> None:
    """Keep the expected HTTP codes and the categories marked transient."""
    assert describe_failure(FailureCategory.PERSISTENCE_FAILURE).http_status == 503
    assert describe_failure(FailureCategory.INVALID_OUTPUT).http_status == 502
    assert describe_failure(FailureCategory.UNEXPECTED).http_status == 500
    assert {
        category for category in FailureCategory if describe_failure(category).is_transient
    } == {
        FailureCategory.SOURCE_UNAVAILABLE,
        FailureCategory.MODEL_UNAVAILABLE,
        FailureCategory.INVALID_OUTPUT,
        FailureCategory.RESEARCHER_FAILURE,
    }
