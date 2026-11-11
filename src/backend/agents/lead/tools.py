"""
Tools the Lead calls to run a group Researcher or the Writer.

Each tool starts a fresh-context Researcher with the group's trusted outlet and
date restrictions. The first call fixes the event window for the whole request;
later calls must reuse it. The tools use the active run's context to record
outcomes and save validated findings and answers."""

import json
import asyncio
import logging

from datetime import UTC, date, datetime
from pydantic import JsonValue
from agents.models.interface import Model
from agents.exceptions import MaxTurnsExceeded
from agents import FunctionTool, ModelSettings, RunContextWrapper, function_tool

from backend.agents.lead.schemas import AspectAlignment
from backend.agents.researcher_findings import SourceGroup
from backend.application.turn.request_state import RequestState
from backend.application.turn.tool_calls import ToolCallOutcome
from backend.application.turn.request_budget import BudgetResource
from backend.application.turn.structured_run import BudgetExceeded
from backend.application.evidence.outlet_assignments import outlet_display_name
from backend.application.evidence.recent_events import (
    EventCandidate,
    discover_events,
    normalize_event_topic,
    start_of_month_window,
)
from backend.agents.research_brief import BriefStatus, ResearchBrief
from backend.agents.researcher.agent import ResearcherOutcome, run_researcher
from backend.application.answer.write_answer import WriteResult, write_answer

logger: logging.Logger = logging.getLogger(__name__)
LEAD_AGENT_NAME: str = "lead"
WRITE_TOOL_NAME: str = "write_answer"
EVENTS_TOOL_NAME: str = "search_recent_events"
RESEARCH_TOOL_NAMES: dict[SourceGroup, str] = {
    group: f"research_{group.value}_coverage" for group in SourceGroup
}


def check_brief(
    state: RequestState,
    event: str,
    start_date: str | None,
    end_date: str | None,
    *,
    today: date | None = None,
) -> tuple[tuple[date, date] | None, str | None]:
    """Validate the brief and fix the event and window on the first call."""
    previous: ResearchBrief | None = state.brief
    try:
        end: date = (
            date.fromisoformat(end_date) if end_date is not None
            else (previous.end_date if previous else None) or today or datetime.now(UTC).date()
        )
        start: date = (
            date.fromisoformat(start_date) if start_date is not None
            else (previous.start_date if previous else None) or start_of_month_window(end)
        )
        brief: ResearchBrief = ResearchBrief.model_validate(
            {
                "status": BriefStatus.CLEAR,
                "event": event,
                "start_date": start,
                "end_date": end,
            }
        )
    except ValueError:
        return None, "The event, start_date, and end_date were not a valid brief."
    assert brief.start_date is not None and brief.end_date is not None
    if previous is None:
        state.brief = brief
    elif (previous.start_date, previous.end_date) != (brief.start_date, brief.end_date):
        return None, "The event window is fixed after the first research call."
    elif previous.event != brief.event:
        return None, "The event is fixed after the first research call."
    return (brief.start_date, brief.end_date), None


def reject_call(
    state: RequestState,
    tool_name: str,
    reason: str,
    args: dict[str, JsonValue],
) -> str:
    """Record a failed Lead tool call and explain it to the Lead."""
    result: str = json.dumps({"status": "failed", "reason": reason})
    state.recorder.record(
        LEAD_AGENT_NAME, tool_name, ToolCallOutcome.FAILURE, reason,
        args=args, result=result,
    )
    return result


async def find_events(
    state: RequestState,
    topic: str | None,
    start_date: str | None,
    end_date: str | None,
    *,
    today: date | None = None,
) -> str:
    """Find dated headlines in a period, newest first regardless of publisher count."""
    args: dict[str, JsonValue] = {
        "topic": topic, "start_date": start_date, "end_date": end_date,
    }
    query: str = normalize_event_topic(topic)
    try:
        end: date = (
            date.fromisoformat(end_date) if end_date is not None
            else today or datetime.now(UTC).date()
        )
        start: date = (
            date.fromisoformat(start_date) if start_date is not None
            else start_of_month_window(end)
        )
    except ValueError:
        return reject_call(state, EVENTS_TOOL_NAME, "Dates must be ISO dates.", args)
    if start > end:
        return reject_call(
            state, EVENTS_TOOL_NAME,
            "The start date must be on or before the end date.",
            args,
        )
    if not state.budget.try_consume(BudgetResource.SEARCH_CALLS):
        return reject_call(state, EVENTS_TOOL_NAME, "The search budget is used up.", args)
    try:
        events: tuple[EventCandidate, ...] = await asyncio.to_thread(
            discover_events, state.sources.discover_headlines, query, start, end,
            require_shared_coverage=False,
        )
    except Exception as error:
        logger.error("Event discovery failed (%s).", type(error).__name__)
        return reject_call(
            state, EVENTS_TOOL_NAME, "Event discovery could not be completed.", args,
        )
    state.event_options = {event.event_id: event for event in events}
    state.events_window = (start, end)
    output: str = json.dumps({
        "status": "ok",
        "search_query": query,
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
    state.recorder.record(
        LEAD_AGENT_NAME, EVENTS_TOOL_NAME, ToolCallOutcome.SUCCESS, args=args, result=output,
    )
    return output


async def research_group(
    state: RequestState,
    group: SourceGroup,
    event: str,
    start_date: str | None,
    end_date: str | None,
    focus_question: str | None,
    model: Model,
    model_settings: ModelSettings | None,
    *,
    today: date,
) -> str:
    """Run a group research round and return findings or a failure as JSON."""
    tool_name: str = RESEARCH_TOOL_NAMES[group]
    args: dict[str, JsonValue] = {
        "event": event, "start_date": start_date, "end_date": end_date,
        "focus_question": focus_question,
    }

    def reject_research(reason: str | None) -> str:
        """Record the failed call and explain it to the Lead."""
        return reject_call(state, tool_name, reason or "No findings were produced.", args)

    window: tuple[date, date] | None
    problem: str | None
    window, problem = check_brief(state, event, start_date, end_date, today=today)
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
    result: str = json.dumps(
        {"status": "ok", "findings": outcome.findings.model_dump(mode="json")}
    )
    state.recorder.record(
        LEAD_AGENT_NAME, tool_name, ToolCallOutcome.SUCCESS, args=args, result=result,
    )
    return result


def build_events_tool(today: date) -> FunctionTool:
    """Build the Lead's tool for finding events in a period."""

    async def run(
        context: RunContextWrapper[RequestState],
        topic: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> str:
        """
        Offer headlines when the reader is deciding what story to research.

        Args:
            topic: Bare location or interest terms for the headline search, such as Paris.
                Omit time phrases. Use null for an unrestricted search.
            start_date: First publication date, ISO format, or null for one month before end_date.
            end_date: Last publication date, ISO format, or null for today."""
        return await find_events(context.context, topic, start_date, end_date, today=today)

    return function_tool(
        run,
        name_override=EVENTS_TOOL_NAME,
        description_override=(
            "Offer headline choices for an open-ended update or an explicit request to "
            "pick a story. For a named subject such as the Paris riots, start both "
            "coverage research tools, including when the subject spans several months."
        ),
    )


def build_research_tool(
    group: SourceGroup,
    model: Model,
    model_settings: ModelSettings | None,
    today: date,
) -> FunctionTool:
    """Build the Lead's research tool for one source group."""

    async def run(
        context: RunContextWrapper[RequestState],
        event: str,
        start_date: str | None,
        end_date: str | None,
        focus_question: str | None,
    ) -> str:
        """
        Research how this group's outlets covered a named event or series of events.

        Args:
            event: The named subject to research, such as the Paris riots.
            start_date: First publication date, ISO format, or null for the default.
            end_date: Last publication date, ISO format, or null for the default.
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
            today=today,
        )

    return function_tool(
        run,
        name_override=RESEARCH_TOOL_NAMES[group],
        description_override=(
            f"Research a named subject with a fresh {group.value} researcher. Use this "
            "alongside the other group's tool for a specific event or series, preserving "
            "the reader's full requested period."
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
            alignment: Comparison rows for a briefing or full report. Use an
                empty list when expanding an earlier answer.
            detailed: True when the reader asks for more detail, a full report,
                sources, or excerpts."""
        state: RequestState = context.context
        result: WriteResult = await write_answer(
            state, model, model_settings, question, alignment, detailed
        )
        state.recorder.record(
            LEAD_AGENT_NAME,
            WRITE_TOOL_NAME,
            ToolCallOutcome.SUCCESS if result.succeeded else ToolCallOutcome.FAILURE,
            None if result.succeeded else result.message,
            args={
                "question": question,
                "alignment": [row.model_dump(mode="json") for row in alignment],
                "detailed": detailed,
            },
            result=result.message,
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
