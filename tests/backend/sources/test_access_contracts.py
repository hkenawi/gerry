"""Test source-result contracts at the boundary consumed by agent tools.

Discovery hints must remain distinct from saved evidence, and partial source
failures must survive serialization without becoming successful article reads."""

import pytest

from datetime import date
from pydantic import ValidationError

from backend.sources.access import ArticleSearchResult


def build_search_payload() -> dict[str, object]:
    """Build partial discovery with one readable outlet and one denied outlet."""
    return {
        "candidates": [
            {
                "outlet_id": "npr",
                "url": "https://www.npr.org/example",
                "title": "Delegations meet for talks",
                "published_at": "2026-11-08",
            },
        ],
        "outcomes": [
            {"outlet_id": "npr", "status": "success"},
            {"outlet_id": "nbc", "status": "access_denied", "http_status": 403},
        ],
    }


def test_search_preserves_candidates_alongside_per_outlet_failures() -> None:
    """Keep successful discovery when a second outlet cannot be accessed."""
    result: ArticleSearchResult = ArticleSearchResult.model_validate(
        build_search_payload(),
    )
    restored: ArticleSearchResult = ArticleSearchResult.model_validate_json(
        result.model_dump_json(),
    )

    assert restored.candidates[0].outlet_id == "npr"
    assert restored.outcomes[1].status == "access_denied"
    assert restored.outcomes[1].http_status == 403
    assert "article_id" not in restored.candidates[0].model_dump()


def test_discovery_preserves_date_only_publication_precision() -> None:
    """Keep discovery dates consistent with the saved-article date contract."""
    result: ArticleSearchResult = ArticleSearchResult.model_validate(
        build_search_payload(),
    )

    assert type(result.candidates[0].published_at) is date


@pytest.mark.parametrize(
    "outcomes",
    [
        [{"outlet_id": "npr", "status": "access_denied"}],
        [{"outlet_id": "nbc", "status": "success"}],
        [
            {"outlet_id": "npr", "status": "success"},
            {"outlet_id": "npr", "status": "access_denied"},
        ],
    ],
)
def test_search_rejects_candidates_with_missing_or_conflicting_outcomes(
    outcomes: list[dict[str, str]],
) -> None:
    """Require one successful outcome for each outlet returning candidates."""
    payload: dict[str, object] = build_search_payload()
    payload["outcomes"] = outcomes

    with pytest.raises(ValidationError):
        ArticleSearchResult.model_validate(payload)
