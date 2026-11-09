"""
Behavior tests for the trusted source tools a Researcher may call.

Outlet assignment, the date window, the shared budget, and retries are all
enforced in code; the model supplies only a query or a URL.
"""

from datetime import date

from backend.agents.researcher_findings import SourceGroup
from backend.agents.researcher.tools import GroupSourceTools
from backend.sources.access import ArticleReadResult, SourceAccessOutcome
from backend.application.settings import Settings

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


async def test_search_is_bound_to_the_groups_outlets_and_the_window(
    make_state,
    fake_sources,
) -> None:
    """
    The model cannot widen the outlets or dates; code supplies both.
    """
    state = make_state()
    tools = build_tools(state)

    await tools.search_articles("France protests")

    call = fake_sources.search_calls[0]
    assert call["assigned_outlets"] == ("npr", "nbc", "huffpost", "abc", "cbs")
    assert (call["start_date"], call["end_date"]) == WINDOW


async def test_search_records_a_tool_call_attributed_to_the_researcher(
    make_state,
) -> None:
    """
    Every search appears in tool_calls with the researcher's agent identity.
    """
    state = make_state()

    await build_tools(state, SourceGroup.CONSERVATIVE).search_articles("x")

    record = state.recorder.records[0]
    assert record.agent == "researcher_conservative"
    assert record.tool == "search_articles"


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


async def test_successful_read_returns_the_saved_article_and_records_success(
    make_state,
    fake_sources,
    make_article,
) -> None:
    """
    A good read returns the article and is recorded as a successful call.
    """
    state = make_state()
    article = make_article("npr")
    fake_sources.read_script = {
        NPR_URL: [
            ArticleReadResult(
                outcome=SourceAccessOutcome(outlet_id="npr", status="success"),
                article=article,
            )
        ]
    }

    result = await build_tools(state).read_article(NPR_URL, "npr")

    assert result.article == article
    assert state.recorder.records[-1].outcome == "success"
    assert state.failed_reads == []
