"""
Group discovered headlines into events reported by several approved outlets.
"""

from datetime import date

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
    from backend.agents.lead.tools import find_events
    from backend.application.settings import Settings

    state = make_state()
    for args in (("x", "not-a-date", None), ("x", "2026-11-09", "2026-11-01"), ("x", "2026-01-01", "2026-11-01")):
        assert '"failed"' in await find_events(state, *args)
    spent = make_state(Settings(max_search_calls=0))
    assert '"failed"' in await find_events(spent, None, None, None)
    assert fake_sources.headline_calls == []
    assert state.events_window is None
