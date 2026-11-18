"""
Tools the Lead calls to run a group Researcher or the Writer.

Each tool starts a fresh-context Researcher with the group's trusted outlet and
date restrictions. The first call fixes the event window for the whole request;
later calls must reuse it. The tools use the active run's context to record
outcomes and save validated findings and answers."""

import json
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
from backend.application.turn.structured_run import BudgetExceeded
from backend.sources.constants import SOURCE_CONSTANTS
from backend.agents.research_brief import BriefStatus, ResearchBrief
from backend.agents.researcher.agent import ResearcherOutcome, run_researcher
from backend.application.answer.write_answer import WriteResult, write_answer

logger: logging.Logger = logging.getLogger(__name__)
LEAD_AGENT_NAME: str = "lead"
WRITE_TOOL_NAME: str = "write_answer"
RESEARCH_TOOL_NAMES: dict[SourceGroup, str] = {
    group: f"research_{group.value}_coverage" for group in SourceGroup
}


def check_brief(
    state: RequestState,
    event: str,
    *,
    today: date | None = None,
) -> tuple[tuple[date, date] | None, str | None]:
    """Validate the brief and fix the event and window on the first call."""
    previous: ResearchBrief | None = state.brief
    if state.issue is not None and event != state.issue.label:
        return None, f"Use the resolved issue label exactly: {state.issue.label!r}."
    try:
        end: date = (previous.end_date if previous else None) or today or datetime.now(UTC).date()
        start: date = (previous.start_date if previous else None) or SOURCE_CONSTANTS.feed_start_date
        brief: ResearchBrief = ResearchBrief.model_validate(
            {
                "status": BriefStatus.CLEAR,
                "event": event,
                "start_date": start,
                "end_date": end,
            }
        )
    except ValueError:
        return None, "The event was not a valid brief."
    assert brief.start_date is not None and brief.end_date is not None
    if previous is None:
        state.brief = brief
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


async def research_group(
    state: RequestState,
    group: SourceGroup,
    event: str,
    focus_question: str | None,
    model: Model,
    model_settings: ModelSettings | None,
    *,
    today: date,
) -> str:
    """Run a group research round and return findings or a failure as JSON."""
    tool_name: str = RESEARCH_TOOL_NAMES[group]
    args: dict[str, JsonValue] = {
        "event": event, "focus_question": focus_question,
    }

    def reject_research(reason: str | None) -> str:
        """Record the failed call and explain it to the Lead."""
        return reject_call(state, tool_name, reason or "No findings were produced.", args)

    window: tuple[date, date] | None
    problem: str | None
    window, problem = check_brief(state, event, today=today)
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
                **({"issue": state.issue} if state.issue is not None else {}),
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
        focus_question: str | None,
    ) -> str:
        """
        Research how this group's outlets covered a named event or series of events.

        Args:
            event: The named subject to research, such as the Paris riots.
            focus_question: A neutral follow-up question, or null for a broad pass."""
        return await research_group(
            context.context,
            group,
            event,
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
            "alongside the other group's tool to search current feeds for the same event."
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
            alignment: Coverage aspects for a briefing or full report. Use an
                empty list for a direct follow-up.
            detailed: True only for an explicit request for a full report."""
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
