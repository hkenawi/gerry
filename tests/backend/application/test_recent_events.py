"""
Group discovered headlines into events reported by several approved outlets.
"""

import json
import pytest

from datetime import date

from backend.agents.lead.tools import find_events
from backend.sources.access import ArticleCandidate
from backend.application.evidence.recent_events import cluster_events


def headline(outlet: str, title: str, day: date | None = date(2026, 11, 6)) -> ArticleCandidate:
    """
    Build one discovered headline.
    """
    return ArticleCandidate(
        outlet_id=outlet, url=f"https://{outlet}.example/{abs(hash(title))}",
        title=title, published_at=day,
    )


def test_events_need_two_distinct_outlets_and_are_ordered_by_outlet_count() -> None:
    """
    A story counts as an event only when different outlets reported it.
    """
    events = cluster_events([
        headline("npr", "Election results announced in Brazil runoff", date(2026, 11, 4)),
        headline("fox", "Brazil runoff election results announced", date(2026, 11, 5)),
        headline("npr", "Powerful earthquake strikes coastal Turkey city", date(2026, 11, 6)),
        headline("nbc", "Earthquake strikes Turkey coastal city, dozens dead", date(2026, 11, 7)),
        headline("cbs", "Turkey earthquake: rescuers search coastal city", date(2026, 11, 7)),
        headline("npr", "Local school board votes on budget", date(2026, 11, 6)),
        headline("npr", "Local school board budget vote delayed", date(2026, 11, 6)),
    ])

    assert [event.event_id for event in events] == [1, 2]
    assert events[0].outlet_ids == ("npr", "nbc", "cbs")
    assert events[0].headline_outlet == "npr"
    assert (events[0].first_date, events[0].last_date) == (date(2026, 11, 6), date(2026, 11, 7))
    assert events[1].outlet_ids == ("npr", "fox")


def test_undated_headlines_are_left_out() -> None:
    """
    An event needs known publication dates, so undated entries never count.
    """
    assert cluster_events([
        headline("npr", "Earthquake strikes coastal Turkey city", None),
        headline("fox", "Coastal Turkey city earthquake strikes", None),
    ]) == ()


def test_candidates_are_capped() -> None:
    """
    Only the best-supported events are offered to the Lead.
    """
    titles = ["alpha bravo charlie", "delta echo foxtrot", "golf hotel india", "juliet kilo lima"]
    candidates = [headline(o, t) for t in titles for o in ("npr", "fox")]

    assert len(cluster_events(candidates, limit=3)) == 3


async def test_event_search_rejects_bad_periods_and_spent_budgets(make_state, fake_sources) -> None:
    """
    The tool checks dates and the search budget in code before touching any source.
    """
    from backend.application.settings import Settings

    state = make_state()
    for args in (("x", "not-a-date", None), ("x", "2026-11-09", "2026-11-01")):
        assert '"failed"' in await find_events(state, *args)
    spent = make_state(Settings(max_search_calls=0))
    assert '"failed"' in await find_events(spent, None, None, None)
    assert fake_sources.headline_calls == []
    assert state.events_window is None


async def test_event_search_defaults_to_a_calendar_month_and_respects_explicit_dates(
    make_state, fake_sources,
) -> None:
    """Use a calendar month for discovery and preserve explicit date ranges."""
    state = make_state()
    default: dict[str, object] = json.loads(await find_events(state, "Paris", None, "2026-03-31"))
    explicit: dict[str, object] = json.loads(await find_events(
        state, "Paris", "2026-01-05", "2026-03-31",
    ))

    assert default["start_date"] == "2026-02-28"
    assert explicit["start_date"] == "2026-01-05"
    assert fake_sources.headline_calls[0]["start_date"] == date(2026, 2, 28)
    assert fake_sources.headline_calls[1]["start_date"] == date(2026, 1, 5)


@pytest.mark.parametrize(("topic", "expected_query"), [
    ("Paris right now ", "Paris"),
    ("events in Paris", "Paris"),
    ("latest headlines from New York this week", "New York"),
    ("Paris climate talks", "Paris climate talks"),
])
async def test_event_search_uses_subject_terms_and_separate_dates(
    topic: str, expected_query: str, make_state, fake_sources,
) -> None:
    """Use the subject alone for feed matching and preserve the requested date bounds."""
    state = make_state()
    result: str = await find_events(state, topic, "2026-11-08", "2026-11-11")

    assert fake_sources.headline_calls == [{
        "query": expected_query, "start_date": date(2026, 11, 8), "end_date": date(2026, 11, 11),
    }]
    assert json.loads(result)["search_query"] == expected_query
    assert state.recorder.records[0].args["topic"] == topic
