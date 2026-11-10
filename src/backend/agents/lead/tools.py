"""
Tools the Lead calls to run a group Researcher or the Writer.

Each tool starts a fresh-context Researcher with the group's trusted outlet and
date restrictions. The first call fixes the event window for the whole request;
later calls must reuse it. The tools use the active run's context to record
outcomes and save validated findings and answers."""

import json

from datetime import date
from pydantic import ValidationError
from agents.models.interface import Model
from agents.exceptions import MaxTurnsExceeded
from agents import FunctionTool, ModelSettings, RunContextWrapper, function_tool

from backend.agents.lead.schemas import AspectAlignment
from backend.agents.researcher_findings import SourceGroup
from backend.application.turn.request_state import RequestState
from backend.application.turn.tool_calls import ToolCallOutcome
from backend.application.turn.structured_run import BudgetExceeded
from backend.agents.research_brief import BriefStatus, ResearchBrief
from backend.agents.researcher.agent import ResearcherOutcome, run_researcher
from backend.application.answer.write_answer import WriteResult, write_answer

LEAD_AGENT_NAME: str = "lead"
WRITE_TOOL_NAME: str = "write_answer"
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
        state.recorder.record(LEAD_AGENT_NAME, tool_name, ToolCallOutcome.FAILURE, reason)
        return json.dumps({
            "status": "failed",
            "reason": reason or "No findings were produced.",
        })

    window: tuple[date, date] | None
    problem: str | None
    window, problem = check_brief(state, event, start_date, end_date)
    if problem is not None or window is None:
        return reject_research(problem)
    if not state.try_start_round(group):
        return reject_research("The research-round limit for this group has been reached.")

    try:
        async with state.research_slots:
            outcome: ResearcherOutcome = await run_researcher(
                state, group, window, event, focus_question, model, model_settings,
            )
    except BudgetExceeded:
        return reject_research("The research limit was reached before this group finished.")
    except MaxTurnsExceeded:
        return reject_research("The researcher ran out of steps before finishing.")
    if outcome.failure is not None or outcome.findings is None:
        return reject_research(outcome.failure)

    brief: ResearchBrief | None = state.brief
    assert brief is not None
    state.findings[group].append(outcome.findings)
    state.store.save_research(
        state.conversation_id,
        brief,
        tuple(item for items in state.findings.values() for item in items),
    )
    state.recorder.record(LEAD_AGENT_NAME, tool_name, ToolCallOutcome.SUCCESS)
    return json.dumps(
        {"status": "ok", "findings": outcome.findings.model_dump(mode="json")}
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
    ) -> str:
        """
        Write the final cited answer from the research collected so far.

        Args:
            question: The reader's question, in plain words.
            alignment: One row per aspect comparing the two groups' coverage."""
        state: RequestState = context.context
        result: WriteResult = await write_answer(
            state, model, model_settings, question, alignment
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
