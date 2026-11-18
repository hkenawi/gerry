"""
Check the code that validates model-proposed topics against the real headlines.
"""

from datetime import date

from backend.sources.access import ArticleCandidate
from backend.agents.topics.schemas import TopicProposal
from backend.application.evidence.topic_clusters import (
    build_topic_options,
    find_proposal_problems,
)


def headline(outlet: str, title: str, day: date | None = date(2026, 11, 6)) -> ArticleCandidate:
    """
    Build one discovered headline with a unique URL.
    """
    return ArticleCandidate(
        outlet_id=outlet, url=f"https://{outlet}.example/{abs(hash(title))}",
        title=title, published_at=day,
    )


def proposal(*topics: tuple[str, list[int]]) -> TopicProposal:
    """
    Build a proposal from label and headline-number pairs.
    """
    return TopicProposal.model_validate({
        "topics": [{"label": label, "headline_numbers": numbers} for label, numbers in topics],
    })


def test_headline_numbers_must_exist_and_belong_to_one_topic() -> None:
    """
    An invented or reused headline number is reported so the model can correct it.
    """
    assert find_proposal_problems(proposal(("Quake response", [1, 2])), 3) is None
    assert "99" in find_proposal_problems(proposal(("Quake response", [1, 99])), 3)
    assert "more than one topic" in find_proposal_problems(
        proposal(("Quake response", [1, 2]), ("Rescue work", [2, 3])), 3,
    )


def test_a_topic_needs_two_outlets_and_is_ranked_by_how_many_covered_it() -> None:
    """
    Single-outlet topics are dropped, and wider coverage comes first.
    """
    candidates = [
        headline("npr", "Earthquake strikes Turkey"),
        headline("fox", "Turkey earthquake kills dozens"),
        headline("cbs", "Rescuers search Turkey rubble"),
        headline("nbc", "Brazil runoff results announced"),
        headline("nypost", "Brazil election runoff decided"),
        headline("npr", "School board budget vote"),
        headline("npr", "School board delays budget"),
    ]

    options = build_topic_options(
        proposal(
            ("Brazil runoff", [4, 5]), ("Turkey earthquake", [1, 2, 3]),
            ("School board budget", [6, 7]),
        ),
        candidates,
    )

    assert [option.label for option in options] == ["Turkey earthquake", "Brazil runoff"]
    assert options[0].outlet_ids == ("npr", "fox", "cbs")
