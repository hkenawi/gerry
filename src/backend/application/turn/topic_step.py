"""
The mandatory first step of every new conversation: propose topics to research.

Before any coverage research starts, the reader's request is turned into a headline
search, the headlines are clustered into a few neutral topics, and the reader picks
one. Code, not the Lead, owns this step so it cannot be skipped. When nothing matches,
the closest related topics are offered instead.
"""

import re
import json
import asyncio
import logging

from agents import ModelSettings
from agents.models.interface import Model
from datetime import UTC, date, datetime

from backend.sources.access import ArticleCandidate
from backend.sources.constants import SourceAccessStatus
from backend.agents.topics.agent import (
    TOPIC_AGENT_MAX_TURNS,
    build_clusterer_agent,
    build_planner_agent,
)
from backend.agents.topics.schemas import TopicProposal, TopicSearch
from backend.agents.researcher_findings import SourceGroup
from backend.application.turn.request_state import RequestState
from backend.application.turn.tool_calls import ToolCallOutcome
from backend.application.turn.request_budget import BudgetResource
from backend.application.turn.structured_run import run_with_correction
from backend.application.answer.answer_rendering import render_topic_options
from backend.application.evidence.outlet_assignments import outlet_display_name, outlets_for_group
from backend.application.evidence.recent_events import (
    headline_terms,
    normalize_event_topic,
    start_of_month_window,
)
from backend.application.evidence.topic_clusters import (
    TopicOption,
    build_topic_options,
    describe_headlines,
    find_proposal_problems,
    rank_related,
    select_headlines,
    word_overlap_topics,
)

logger: logging.Logger = logging.getLogger(__name__)
LEAD_AGENT_NAME: str = "lead"
SEARCH_TOOL_NAME: str = "search_recent_events"
GROUP_TOOL_NAME: str = "group_topics"
MINIMUM_TOPICS: int = 2
HEADLINES_UNAVAILABLE: str = "Recent headlines could not be loaded. Please try again shortly."
TOPIC_SELECTION: re.Pattern[str] = re.compile(
    r"How did different outlets cover “.+” from \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}\?",
)


def is_topic_selection(question: str) -> bool:
    """
    Tell whether a message is a chosen topic, or a front-page headline, to research.
    """
    return TOPIC_SELECTION.fullmatch(" ".join(question.split())) is not None


async def plan_search(
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None,
    question: str,
    today: date,
) -> tuple[str, date, date]:
    """Extract the subject and period from the request, falling back to defaults."""
    plan: TopicSearch | None = None

    def validate(output: TopicSearch) -> str | None:
        """Require a coherent period when both dates are given."""
        if output.start_date and output.end_date and output.start_date > output.end_date:
            return "start_date must be on or before end_date."
        return None

    plan, _ = await run_with_correction(
        build_planner_agent(model, model_settings, today),
        [{"role": "user", "content": question}],
        state, validate, TOPIC_AGENT_MAX_TURNS,
    )
    topic: str = normalize_event_topic(plan.topic if plan else None)
    end: date = (plan.end_date if plan else None) or today
    start: date = (plan.start_date if plan else None) or start_of_month_window(end)
    if start > end:
        start = start_of_month_window(end)
    return topic, start, end


async def search_headlines(
    state: RequestState,
    topic: str,
    start: date,
    end: date,
) -> list[ArticleCandidate] | None:
    """Collect dated headlines across the approved outlets, or None on failure."""
    args: dict[str, str | None] = {
        "topic": topic or None, "start_date": start.isoformat(), "end_date": end.isoformat(),
    }
    if not state.budget.try_consume(BudgetResource.SEARCH_CALLS):
        state.recorder.record(
            LEAD_AGENT_NAME, SEARCH_TOOL_NAME, ToolCallOutcome.FAILURE,
            "The search budget is used up.", args=args,
        )
        return None
    outlets: tuple[str, ...] = tuple(
        outlet for group in SourceGroup for outlet in outlets_for_group(group)
    )
    try:
        result = await asyncio.to_thread(
            state.sources.discover_headlines, topic, start, end, outlets,
        )
        if not any(
            o.status in (SourceAccessStatus.SUCCESS, SourceAccessStatus.NO_RESULTS)
            for o in result.outcomes
        ):
            raise RuntimeError("No approved publisher could be searched.")
    except Exception as error:
        logger.exception("Headline search failed (%s).", type(error).__name__)
        state.recorder.record(
            LEAD_AGENT_NAME, SEARCH_TOOL_NAME, ToolCallOutcome.FAILURE,
            "Headline search could not be completed.", args=args,
        )
        return None
    candidates: list[ArticleCandidate] = list(result.candidates)
    state.recorder.record(
        LEAD_AGENT_NAME, SEARCH_TOOL_NAME, ToolCallOutcome.SUCCESS, args=args,
        result=json.dumps({"status": "ok", "headlines": len(candidates)}),
    )
    return candidates


async def cluster_topics(
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None,
    candidates: list[ArticleCandidate],
    query_terms: frozenset[str],
) -> tuple[TopicOption, ...] | None:
    """Group headlines into validated topics, or None when the model's output was unusable."""
    chosen: list[ArticleCandidate] = select_headlines(candidates, query_terms)
    if not chosen:
        return ()
    names: dict[str, str] = {item.outlet_id: outlet_display_name(item.outlet_id) for item in chosen}
    proposal: TopicProposal | None
    proposal, problem = await run_with_correction(
        build_clusterer_agent(model, model_settings),
        [{"role": "user", "content": "Headlines:\n" + describe_headlines(chosen, names)}],
        state,
        lambda output: find_proposal_problems(output, len(chosen)),
        TOPIC_AGENT_MAX_TURNS,
    )
    if proposal is None:
        logger.error("Topic clustering failed: %s", problem)
        state.recorder.record(
            LEAD_AGENT_NAME, GROUP_TOOL_NAME, ToolCallOutcome.FAILURE,
            "The headlines could not be grouped into topics.",
        )
        return None
    options: tuple[TopicOption, ...] = build_topic_options(proposal, chosen)
    state.recorder.record(
        LEAD_AGENT_NAME, GROUP_TOOL_NAME, ToolCallOutcome.SUCCESS,
        result=json.dumps({"status": "ok", "topics": [option.label for option in options]}),
    )
    return options


async def propose_topics(
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None,
    question: str,
    today: date | None = None,
) -> str:
    """
    Return Markdown topic choices for a request. It always offers topics when any recent
    headlines are reachable, falling back to related topics and then to word-overlap groups.
    """
    current: date = today or datetime.now(UTC).date()
    topic: str
    start: date
    end: date
    topic, start, end = await plan_search(state, model, model_settings, question, current)
    query_terms: frozenset[str] = headline_terms(topic or "")

    matches: list[ArticleCandidate] | None = await search_headlines(state, topic, start, end)
    if matches is None:
        return HEADLINES_UNAVAILABLE
    found: tuple[TopicOption, ...] = await cluster_topics(
        state, model, model_settings, matches, query_terms,
    ) or ()
    related: tuple[TopicOption, ...] = ()
    pool: list[ArticleCandidate] = matches
    if len(found) < MINIMUM_TOPICS and topic:
        everything: list[ArticleCandidate] | None = await search_headlines(state, "", start, end)
        if everything:
            pool = everything
            related = rank_related(
                await cluster_topics(state, model, model_settings, pool, query_terms) or (),
                query_terms, exclude=found,
            )
    if not found and not related:
        related = rank_related(word_overlap_topics(pool), query_terms)
    return render_topic_options(found, related, (start, end), topic)
