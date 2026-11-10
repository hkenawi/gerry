"""Test the saved article boundary consumed by research and citation code.

These offline tests validate snapshot integrity and compatibility with Person A's
findings, without fetching sources or choosing a persistence backend."""

import pytest

from uuid import UUID
from datetime import date, datetime
from pydantic import ValidationError

from backend.sources.articles import ArticleRecord
from backend.sources.access import ArticleReadResult


ARTICLE_ID: UUID = UUID("6ea317ce-d5c4-43ea-9ae8-d6c597af8b04")
FIRST_PASSAGE_ID: str = f"{ARTICLE_ID}:p0001"


def build_article_payload() -> dict[str, object]:
    """Build a reporting snapshot with two paragraphs and a date-only publication."""
    return {
        "article_id": str(ARTICLE_ID),
        "outlet_id": "npr",
        "requested_url": "https://www.npr.org/example",
        "canonical_url": "https://www.npr.org/example",
        "title": "Delegations meet for talks",
        "bylines": ["Example Reporter"],
        "published_at": "2026-11-08",
        "retrieved_at": "2026-11-08T21:00:00Z",
        "article_type": "reporting",
        "passages": [
            {"passage_id": FIRST_PASSAGE_ID, "text": "Delegations met on Sunday."},
            {
                "passage_id": f"{ARTICLE_ID}:p0002",
                "text": "Officials described the agenda.",
            },
        ],
    }


def test_saved_article_round_trip_preserves_evidence_and_date_precision() -> None:
    """Reload a snapshot without changing its evidence IDs, text, or date precision."""
    article: ArticleRecord = ArticleRecord.model_validate(build_article_payload())
    restored: ArticleRecord = ArticleRecord.model_validate_json(
        article.model_dump_json(),
    )

    assert restored == article
    assert type(restored.published_at) is date
    assert restored.passages[0].passage_id == FIRST_PASSAGE_ID
    assert restored.passages[1].text == "Officials described the agenda."


@pytest.mark.parametrize(
    "passages",
    [
        [],
        [{"passage_id": FIRST_PASSAGE_ID, "text": "   "}],
        [{"passage_id": "another-article:p0001", "text": "Wrong article."}],
        [
            {"passage_id": FIRST_PASSAGE_ID, "text": "First paragraph."},
            {"passage_id": FIRST_PASSAGE_ID, "text": "Reused reference."},
        ],
    ],
)
def test_article_rejects_unusable_or_ambiguous_passage_references(
    passages: list[dict[str, str]],
) -> None:
    """Reject empty evidence and references that cannot identify one paragraph."""
    payload: dict[str, object] = build_article_payload()
    payload["passages"] = passages

    with pytest.raises(ValidationError):
        ArticleRecord.model_validate(payload)


def test_saved_article_rejects_evidence_changes() -> None:
    """Prevent modifying a saved snapshot behind existing citation references."""
    article: ArticleRecord = ArticleRecord.model_validate(build_article_payload())

    with pytest.raises(ValidationError):
        setattr(article, "passages", ())


@pytest.mark.parametrize(
    "status, include_article",
    [("success", False), ("storage_failed", True)],
)
def test_article_read_cannot_misrepresent_missing_or_failed_evidence(
    status: str,
    include_article: bool,
) -> None:
    """Reject empty successes and failed reads presented with usable evidence."""
    payload: dict[str, object] = {
        "outcome": {"outlet_id": "npr", "status": status},
        "article": build_article_payload() if include_article else None,
    }

    with pytest.raises(ValidationError):
        ArticleReadResult.model_validate(payload)


def test_article_read_rejects_evidence_from_another_outlet() -> None:
    """Do not attribute an NPR snapshot to a different outlet's successful read."""
    with pytest.raises(ValidationError):
        ArticleReadResult.model_validate(
            {
                "outcome": {"outlet_id": "fox", "status": "success"},
                "article": build_article_payload(),
            },
        )


def test_article_normalizes_retrieval_time_without_changing_publication_day() -> None:
    """Use UTC for retrieval while retaining the publisher's calendar date."""
    payload: dict[str, object] = build_article_payload()
    payload["published_at"] = "2026-11-07T23:30:00-05:00"
    payload["retrieved_at"] = "2026-11-08T18:00:00-05:00"
    article: ArticleRecord = ArticleRecord.model_validate(payload)

    assert article.published_at is not None
    assert article.published_at.isoformat() == "2026-11-07T23:30:00-05:00"
    assert article.retrieved_at.isoformat() == "2026-11-08T23:00:00+00:00"


@pytest.mark.parametrize(
    ("field_name", "naive_timestamp"),
    [
        ("published_at", "2026-11-08T12:00:00"),
        ("updated_at", datetime(2026, 11, 8, 12)),
        ("retrieved_at", "2026-11-08T12:00:00"),
    ],
)
def test_article_rejects_timestamps_without_timezone(
    field_name: str,
    naive_timestamp: str | datetime,
) -> None:
    """Reject ambiguous timestamps rather than assuming a publisher timezone."""
    payload: dict[str, object] = build_article_payload()
    payload[field_name] = naive_timestamp

    with pytest.raises(ValidationError):
        ArticleRecord.model_validate(payload)
