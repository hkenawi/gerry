"""
Tools the Lead calls to run a group Researcher or the Writer.

Each tool starts a fresh-context Researcher with the group's trusted outlet and
date restrictions. The first call fixes the event window for the whole request;
later calls must reuse it. The tools use the active run's context to record
outcomes and save validated findings and answers."""

import json
import asyncio
import logging

from datetime import UTC, date, datetime, timedelta
from pydantic import ValidationError
from agents.models.interface import Model
from agents.exceptions import MaxTurnsExceeded
from agents import FunctionTool, ModelSettings, RunContextWrapper, function_tool

from backend.agents.lead.schemas import AspectAlignment
from backend.agents.researcher_findings import SourceGroup
from backend.application.turn.request_state import RequestState
from backend.application.turn.tool_calls import ToolCallOutcome
from backend.application.turn.request_budget import BudgetResource
from backend.application.turn.structured_run import BudgetExceeded
from backend.application.evidence.recent_events import cluster_events
from backend.application.evidence.outlet_assignments import outlet_display_name, outlets_for_group
from backend.agents.research_brief import BriefStatus, ResearchBrief
from backend.agents.researcher.agent import ResearcherOutcome, run_researcher
from backend.application.answer.write_answer import WriteResult, write_answer

logger: logging.Logger = logging.getLogger(__name__)
LEAD_AGENT_NAME: str = "lead"
WRITE_TOOL_NAME: str = "write_answer"
EVENTS_TOOL_NAME: str = "search_recent_events"
RECENT_EVENT_DAYS: int = 7
MAX_EVENT_WINDOW_DAYS: int = 31
RESEARCH_TOOL_NAMES: dict[SourceGroup, str] = {
    group: f"research_{group.value}_coverage" for group in SourceGroup
}


def check_brief(
    state: RequestState,
    event: str,
    start_date: str,
    end_date: str,
) -> tuple[tuple[date, date] | None, str | None]:
    """Validate the brief and fix the event and window on the first call."""
    try:
        brief: ResearchBrief = ResearchBrief.model_validate(
            {
                "status": BriefStatus.CLEAR,
                "event": event,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
    except ValidationError:
        return None, "The event, start_date, and end_date were not a valid brief."
    assert brief.start_date is not None and brief.end_date is not None
    previous: ResearchBrief | None = state.brief
    if previous is None:
        state.brief = brief
    elif (previous.start_date, previous.end_date) != (brief.start_date, brief.end_date):
        return None, "The event window is fixed after the first research call."
    elif previous.event != brief.event:
        return None, "The event is fixed after the first research call."
    return (brief.start_date, brief.end_date), None


def reject_call(state: RequestState, tool_name: str, reason: str) -> str:
    """Record a failed Lead tool call and explain it to the Lead."""
    state.recorder.record(LEAD_AGENT_NAME, tool_name, ToolCallOutcome.FAILURE, reason)
    return json.dumps({"status": "failed", "reason": reason})


async def find_events(
    state: RequestState,
    topic: str | None,
    start_date: str | None,
    end_date: str | None,
) -> str:
    """Find events several approved outlets reported in a period, default the past week."""
    try:
        end: date = date.fromisoformat(end_date) if end_date else datetime.now(UTC).date()
        start: date = (
            date.fromisoformat(start_date) if start_date
            else end - timedelta(days=RECENT_EVENT_DAYS)
        )
    except ValueError:
        return reject_call(state, EVENTS_TOOL_NAME, "Dates must be ISO dates.")
    if not 0 <= (end - start).days <= MAX_EVENT_WINDOW_DAYS:
        return reject_call(
            state, EVENTS_TOOL_NAME,
            f"The period must run forward and span at most {MAX_EVENT_WINDOW_DAYS} days.",
        )
    if not state.budget.try_consume(BudgetResource.SEARCH_CALLS):
        return reject_call(state, EVENTS_TOOL_NAME, "The search budget is used up.")
    try:
        result = await asyncio.to_thread(
            state.sources.discover_headlines, topic or "", start, end,
            tuple(outlet for group in SourceGroup for outlet in outlets_for_group(group)),
        )
    except Exception as error:
        logger.error("Event discovery failed (%s).", type(error).__name__)
        return reject_call(state, EVENTS_TOOL_NAME, "Event discovery could not be completed.")
    events = cluster_events(list(result.candidates))
    state.event_options = {event.event_id: event for event in events}
    state.events_window = (start, end)
    state.recorder.record(LEAD_AGENT_NAME, EVENTS_TOOL_NAME, ToolCallOutcome.SUCCESS)
    return json.dumps({
        "status": "ok",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "events": [
            {
                "event_id": event.event_id,
                "headline": event.headline,
                "reported_by": [outlet_display_name(o) for o in event.outlet_ids],
                "first_date": event.first_date.isoformat(),
                "last_date": event.last_date.isoformat(),
            }
            for event in events
        ],
    })


async def research_group(
    state: RequestState,
    group: SourceGroup,
    event: str,
    start_date: str,
    end_date: str,
    focus_question: str | None,
    model: Model,
    model_settings: ModelSettings | None,
) -> str:
    """Run a group research round and return findings or a failure as JSON."""
    tool_name: str = RESEARCH_TOOL_NAMES[group]

    def reject_research(reason: str | None) -> str:
        """Record the failed call and explain it to the Lead."""
        return reject_call(state, tool_name, reason or "No findings were produced.")

    window: tuple[date, date] | None
    problem: str | None
    window, problem = check_brief(state, event, start_date, end_date)
    if problem is not None or window is None:
        return reject_research(problem)
    if not state.try_start_round(group):
        return reject_research("The research-round limit for this group has been reached.")

    brief: ResearchBrief | None = state.brief
    assert brief is not None
    try:
        async with state.research_slots:
            outcome: ResearcherOutcome = await run_researcher(
                state, group, window, event, focus_question, model, model_settings,
            )
        if outcome.findings is not None:
            state.store.save_research(
                state.conversation_id,
                brief,
                (*(item for items in state.findings.values() for item in items), outcome.findings),
            )
    except BudgetExceeded:
        return reject_research("The research limit was reached before this group finished.")
    except MaxTurnsExceeded:
        return reject_research("The researcher ran out of steps before finishing.")
    except Exception as error:
        logger.error("Research for %s failed (%s).", group.value, type(error).__name__)
        return reject_research("This group's research could not be completed.")
    if outcome.failure is not None or outcome.findings is None:
        return reject_research(outcome.failure)

    state.findings[group].append(outcome.findings)
    state.recorder.record(LEAD_AGENT_NAME, tool_name, ToolCallOutcome.SUCCESS)
    return json.dumps(
        {"status": "ok", "findings": outcome.findings.model_dump(mode="json")}
    )


def build_events_tool() -> FunctionTool:
    """Build the Lead's tool for finding events in a period."""

    async def run(
        context: RunContextWrapper[RequestState],
        topic: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> str:
        """
        Find international events that several approved outlets reported in a period.

        Args:
            topic: Words narrowing the search, or null to list every event.
            start_date: First publication date, ISO format, or null for seven days ago.
            end_date: Last publication date, ISO format, or null for today."""
        return await find_events(context.context, topic, start_date, end_date)

    return function_tool(
        run,
        name_override=EVENTS_TOOL_NAME,
        description_override=(
            "List events that at least two approved outlets reported in a period. "
            "Use it to offer recent events or to find which event a reader means."
        ),
    )


def build_research_tool(
    group: SourceGroup,
    model: Model,
    model_settings: ModelSettings | None,
) -> FunctionTool:
    """Build the Lead's research tool for one source group."""

    async def run(
        context: RunContextWrapper[RequestState],
        event: str,
        start_date: str,
        end_date: str,
        focus_question: str | None,
    ) -> str:
        """
        Research how this group's outlets covered the event.

        Args:
            event: The event to research, in plain words.
            start_date: First publication date, ISO format, inclusive.
            end_date: Last publication date, ISO format, inclusive.
            focus_question: A neutral follow-up question, or null for a broad pass."""
        return await research_group(
            context.context,
            group,
            event,
            start_date,
            end_date,
            focus_question,
            model,
            model_settings,
        )

    return function_tool(
        run,
        name_override=RESEARCH_TOOL_NAMES[group],
        description_override=(
            f"Run a fresh {group.value} researcher over its assigned outlets "
            "and return validated findings."
        ),
    )


def build_writer_tool(
    model: Model,
    model_settings: ModelSettings | None,
) -> FunctionTool:
    """Build the Lead's tool for producing the final cited answer."""

    async def run(
        context: RunContextWrapper[RequestState],
        question: str,
        alignment: list[AspectAlignment],
        detailed: bool = False,
    ) -> str:
        """
        Write the final cited answer from the research collected so far.

        Args:
            question: The reader's question, in plain words.
            alignment: One row per aspect comparing the two groups' coverage.
            detailed: True only when the reader asked for a detailed or full report."""
        state: RequestState = context.context
        result: WriteResult = await write_answer(
            state, model, model_settings, question, alignment, detailed
        )
        state.recorder.record(
            LEAD_AGENT_NAME,
            WRITE_TOOL_NAME,
            ToolCallOutcome.SUCCESS if result.succeeded else ToolCallOutcome.FAILURE,
            None if result.succeeded else result.message,
        )
        return result.message

    return function_tool(
        run,
        name_override=WRITE_TOOL_NAME,
        description_override=(
            "Have the Writer produce the final cited answer from the collected "
            "research. Call it once research is finished."
        ),
    )
