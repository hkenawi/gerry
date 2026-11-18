"""
Behavior tests for the trusted source tools a Researcher may call.

The tests protect outlet restrictions, shared search and read budgets, and
bounded retries for the model's source tools."""

from datetime import date

from backend.application.settings import Settings
from backend.agents.researcher_findings import SourceGroup
from backend.agents.researcher.tools import GroupSourceTools
from backend.sources.access import (
    ArticleReadResult,
    SourceAccessOutcome,
)

WINDOW: tuple[date, date] = (date(2026, 11, 1), date(2026, 11, 7))
NPR_URL: str = "https://npr.example/a"


def build_tools(state, group: SourceGroup = SourceGroup.LIBERAL) -> GroupSourceTools:
    """
    Build tools bound to one group and the fixed event window.
    """
    return GroupSourceTools(state=state, group=group, window=WINDOW)


def failed_read(outlet_id: str, status: str) -> ArticleReadResult:
    """
    Build a failed read result for one outlet.
    """
    return ArticleReadResult(
        outcome=SourceAccessOutcome(outlet_id=outlet_id, status=status)
    )


async def test_search_with_spent_budget_does_not_call_the_source(
    make_state,
    fake_sources,
) -> None:
    """
    Once the search budget is spent, no external call is made.
    """
    state = make_state(Settings(max_search_calls=1))
    tools = build_tools(state)
    await tools.search_articles("first")

    result = await tools.search_articles("second")

    assert len(fake_sources.search_calls) == 1
    assert result.outcomes[0].status == "budget_exhausted"


async def test_read_outside_the_groups_outlets_is_refused_without_a_call(
    make_state,
    fake_sources,
) -> None:
    """
    A liberal researcher cannot read a conservative outlet even if asked.
    """
    state = make_state()

    result = await build_tools(state).read_article("https://fox.example/a", "fox")

    assert fake_sources.read_calls == []
    assert result.outcome.status == "access_denied"
    assert state.failed_reads[0].outlet_id == "fox"


async def test_transient_fetch_failures_are_retried_within_the_ceiling(
    make_state,
    fake_sources,
) -> None:
    """
    A fetch failure is retried up to max_retries and then reported, once.
    """
    state = make_state(Settings(max_retries=2))
    fake_sources.read_script = {NPR_URL: [failed_read("npr", "fetch_failed")] * 3}

    result = await build_tools(state).read_article(NPR_URL, "npr")

    assert len(fake_sources.read_calls) == 3
    assert result.outcome.status == "fetch_failed"
    assert len(state.failed_reads) == 1


async def test_non_transient_failures_are_not_retried(
    make_state,
    fake_sources,
) -> None:
    """
    A paywall will not change on retry, so only one attempt is made.
    """
    state = make_state(Settings(max_retries=2))
    fake_sources.read_script = {NPR_URL: [failed_read("npr", "paywall")]}

    await build_tools(state).read_article(NPR_URL, "npr")

    assert len(fake_sources.read_calls) == 1


async def test_retries_consume_the_shared_read_budget(
    make_state,
    fake_sources,
) -> None:
    """
    Retries cannot stack beyond the request-wide article-read budget.
    """
    state = make_state(Settings(max_retries=5, max_article_reads=2))
    fake_sources.read_script = {NPR_URL: [failed_read("npr", "fetch_failed")] * 5}

    result = await build_tools(state).read_article(NPR_URL, "npr")

    assert len(fake_sources.read_calls) == 2
    assert result.outcome.status == "budget_exhausted"
