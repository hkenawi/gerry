"""Run topic discovery before the Lead starts coverage research.

The discovery agent searches approved outlets and proposes groups of numbered
headlines. This module owns search limits, validates the groups against the
retrieved headlines, and broadens the search when too few topics match."""

import json
import asyncio
import logging

from uuid import UUID
from dataclasses import dataclass
from datetime import UTC, date, datetime
from openai import APIError
from agents.models.interface import Model
from agents.exceptions import MaxTurnsExceeded
from agents import Agent, AgentBase, ModelSettings, RunContextWrapper, function_tool
from backend.agents.research_issue import ResearchIssue

from backend.sources.access import ArticleCandidate
from backend.sources.constants import SOURCE_CONSTANTS, SourceAccessStatus
from backend.agents.topics.agent import (
    TOPIC_AGENT_CONSTANTS,
    TOPIC_AGENT_MAX_TURNS,
    build_topic_discovery_agent,
)
from backend.agents.topics.schemas import TOPIC_RESOLUTION, IssueResolution, TopicProposal
from backend.agents.researcher_findings import SourceGroup
from backend.application.turn.request_state import RequestState
from backend.application.turn.tool_calls import ToolCallOutcome
from backend.application.turn.request_budget import BudgetResource
from backend.application.turn.structured_run import BudgetExceeded, run_with_correction
from backend.application.answer.answer_rendering import FEED_SCOPE_NOTICE, render_topic_options
from backend.application.evidence.outlet_assignments import outlet_display_name, outlets_for_group
from backend.application.evidence.recent_events import headline_terms, normalize_event_topic
from backend.application.evidence.topic_clusters import (
    TopicOption,
    build_topic_options,
    describe_headlines,
    find_feed_issue_problems,
    find_proposal_problems,
    select_headlines,
    word_overlap_topics,
)

logger: logging.Logger = logging.getLogger(__name__)
MOST_COVERED_LIMIT: int = 3
HEADLINES_UNAVAILABLE: str = "Recent headlines could not be loaded. Please try again shortly."
EDITION_HEADLINE_LIMIT: int = 100
EDITION_GROUPING_SECONDS: float = 20.0


@dataclass(frozen=True)
class IssueDiscovery:
    """Return either a ready issue or reader-facing choices for the turn."""

    answer: str = ""
    issue: ResearchIssue | None = None


@dataclass(frozen=True)
class HeadlineSearch:
    """Keep the effective subject and the exact headlines used by the agent."""

    topic: str
    date_filter_requested: bool
    candidates: list[ArticleCandidate] | None
    numbered: list[ArticleCandidate]


async def search_headlines(
    state: RequestState,
    topic: str,
    today: date,
) -> list[ArticleCandidate] | None:
    """Collect current feed headlines across the approved outlets, or None on failure."""
    args: dict[str, str | None] = {"topic": topic or None}
    if not state.budget.try_consume(BudgetResource.SEARCH_CALLS):
        state.recorder.record(
            TOPIC_AGENT_CONSTANTS.activity.AGENT.value,
            TOPIC_AGENT_CONSTANTS.activity.SEARCH.value,
            ToolCallOutcome.FAILURE,
            "The search budget is used up.", args=args,
        )
        return None
    outlets: tuple[str, ...] = tuple(
        outlet for group in SourceGroup for outlet in outlets_for_group(group)
    )
    try:
        result = await asyncio.to_thread(
            state.sources.discover_headlines,
            topic,
            SOURCE_CONSTANTS.feed_start_date,
            today,
            outlets,
        )
        if not any(
            o.status in (SourceAccessStatus.SUCCESS, SourceAccessStatus.NO_RESULTS)
            for o in result.outcomes
        ):
            raise RuntimeError("No approved publisher could be searched.")
    except Exception as error:
        logger.exception("Headline search failed (%s).", type(error).__name__)
        state.recorder.record(
            TOPIC_AGENT_CONSTANTS.activity.AGENT.value,
            TOPIC_AGENT_CONSTANTS.activity.SEARCH.value,
            ToolCallOutcome.FAILURE,
            "Headline search could not be completed.", args=args,
        )
        return None
    candidates: list[ArticleCandidate] = list(result.candidates)
    state.recorder.record(
        TOPIC_AGENT_CONSTANTS.activity.AGENT.value,
        TOPIC_AGENT_CONSTANTS.activity.SEARCH.value,
        ToolCallOutcome.SUCCESS,
        args=args,
        result=json.dumps({"status": "ok", "headlines": len(candidates)}),
    )
    return candidates


def render_numbered_headlines(headlines: list[ArticleCandidate]) -> str:
    """Describe the exact headline list used to validate the agent's references."""
    names: dict[str, str] = {
        item.outlet_id: outlet_display_name(item.outlet_id) for item in headlines
    }
    return describe_headlines(headlines, names)


def collect_topic_options(
    state: RequestState,
    proposal: TopicProposal | None,
    problem: str | None,
    numbered: list[ArticleCandidate],
) -> tuple[TopicOption, ...]:
    """Convert a checked proposal into topic choices and record the grouping outcome."""
    if not numbered:
        return ()
    if proposal is None:
        logger.error("Topic clustering failed: %s", problem)
        state.recorder.record(
            TOPIC_AGENT_CONSTANTS.activity.AGENT.value,
            TOPIC_AGENT_CONSTANTS.activity.GROUP.value,
            ToolCallOutcome.FAILURE,
            "The headlines could not be grouped into topics.",
        )
        return ()
    options: tuple[TopicOption, ...] = build_topic_options(
        proposal,
        numbered,
        minimum_outlets=1 if proposal.resolution in (
            TOPIC_RESOLUTION.resolutions.READY,
            TOPIC_RESOLUTION.resolutions.BROADEN,
        ) else 2,
    )
    state.recorder.record(
        TOPIC_AGENT_CONSTANTS.activity.AGENT.value,
        TOPIC_AGENT_CONSTANTS.activity.GROUP.value,
        ToolCallOutcome.SUCCESS,
        result=json.dumps({"status": "ok", "topics": [option.label for option in options]}),
    )
    return options


def prepare_research_issue(option: TopicOption) -> ResearchIssue:
    """Keep the neutral issue definition and exact feed candidates together."""
    return ResearchIssue(option.label, option.description, option.candidates)


async def group_feed_issues(
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None,
    today: date,
    headlines: list[ArticleCandidate],
) -> tuple[TopicOption, ...]:
    """Use the same issue definition for front-page and fallback feed suggestions."""
    numbered: list[ArticleCandidate] = select_headlines(headlines, limit=EDITION_HEADLINE_LIMIT)
    if not numbered:
        return ()
    proposal: TopicProposal | None
    try:
        proposal, _ = await asyncio.wait_for(
            run_with_correction(
                build_topic_discovery_agent(model, model_settings, today),
                [{"role": "user", "content": "Headlines:\n" + render_numbered_headlines(numbered)}],
                state,
                lambda output: find_feed_issue_problems(output, numbered),
                TOPIC_AGENT_MAX_TURNS,
            ),
            timeout=min(EDITION_GROUPING_SECONDS, state.budget.remaining_seconds()),
        )
    except (APIError, BudgetExceeded, MaxTurnsExceeded, TimeoutError):
        return ()
    return (
        tuple(option for option in build_topic_options(proposal, numbered) if option.description)
        if proposal else ()
    )


async def propose_topics(
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None,
    question: str,
    today: date | None = None,
) -> IssueDiscovery:
    """Return topic choices using the discovery agent and bounded search fallbacks."""
    current: date = today or datetime.now(UTC).date()
    primary: HeadlineSearch | None = None
    search_started: bool = False

    def can_search_headlines(
        _context: RunContextWrapper[RequestState],
        _agent: AgentBase,
    ) -> bool:
        """Expose search until the application has started the primary search."""
        return not search_started

    async def search_recent_events(
        context: RunContextWrapper[RequestState],
        topic: str | None = None,
        date_filter_requested: bool = False,
        alternatives: list[str] | None = None,
    ) -> str:
        """Find numbered headlines in current feeds; flag any requested date filter."""
        nonlocal primary, search_started
        if search_started:
            return "Use the result of the first headline search."
        search_started = True
        query: str = normalize_event_topic(topic)
        variants: str = " | ".join(dict.fromkeys((query, *(alternatives or [])[:4]))) if query else ""
        candidates: list[ArticleCandidate] | None = await search_headlines(
            context.context, variants, current,
        )
        numbered: list[ArticleCandidate] = select_headlines(
            candidates or [], headline_terms(query),
        )
        primary = HeadlineSearch(query, date_filter_requested, candidates, numbered)
        return render_numbered_headlines(numbered)

    def validate_primary_proposal(output: TopicProposal) -> str | None:
        """Require a search and restrict topics to the headlines it returned."""
        if primary is None:
            return f"Call {TOPIC_AGENT_CONSTANTS.activity.SEARCH.value} before proposing topics."
        if output.resolution is TOPIC_RESOLUTION.resolutions.READY and (
            len(output.topics) != 1 or not output.topics[0].description.strip()
        ):
            return "A ready issue needs exactly one neutral topic and a scope description."
        return find_proposal_problems(output, len(primary.numbered))

    agent: Agent[RequestState] = build_topic_discovery_agent(
        model,
        model_settings,
        current,
        function_tool(
            search_recent_events,
            name_override=TOPIC_AGENT_CONSTANTS.activity.SEARCH.value,
            is_enabled=can_search_headlines,
        ),
    )
    proposal: TopicProposal | None
    problem: str | None
    proposal, problem = await run_with_correction(
        agent,
        [{"role": "user", "content": question}],
        state,
        validate_primary_proposal,
        TOPIC_AGENT_MAX_TURNS,
    )

    if primary is None:
        candidates: list[ArticleCandidate] | None = await search_headlines(state, "", current)
        primary = HeadlineSearch("", False, candidates, [])
    if primary.candidates is None:
        return IssueDiscovery(HEADLINES_UNAVAILABLE)

    found: tuple[TopicOption, ...] = collect_topic_options(
        state, proposal, problem, primary.numbered,
    ) or word_overlap_topics(primary.candidates)
    resolution: IssueResolution = (
        proposal.resolution if proposal else TOPIC_RESOLUTION.resolutions.NARROW
    )
    if found and resolution is TOPIC_RESOLUTION.resolutions.READY:
        return IssueDiscovery(
            FEED_SCOPE_NOTICE if primary.date_filter_requested else "",
            prepare_research_issue(found[0]),
        )
    most_covered: tuple[TopicOption, ...] = ()
    if not found and primary.topic:
        everything: list[ArticleCandidate] | None = await search_headlines(state, "", current)
        grouped: tuple[TopicOption, ...] = await group_feed_issues(
            state, model, model_settings, current, everything or [],
        )
        most_covered = (grouped or word_overlap_topics(everything or []))[:MOST_COVERED_LIMIT]
    shown: tuple[TopicOption, ...] = found or most_covered
    issue_ids: tuple[UUID | None, ...] = tuple(
        state.store.publish_issue(prepare_research_issue(option))
        for option in shown
    )
    return IssueDiscovery(render_topic_options(
        found,
        most_covered,
        primary.topic,
        primary.date_filter_requested,
        resolution=resolution,
        issue_ids=issue_ids,
    ))
