"""
Research tools the Lead calls to run a Researcher for one source group.

Each tool starts a fresh-context Researcher with the group's trusted outlet and
date restrictions. The first call fixes the event window for the whole request;
later calls must reuse it. Findings are saved by code, never by the model.
"""

import json
from datetime import date
from typing import Awaitable, Callable

from agents import FunctionTool, ModelSettings, function_tool
from agents.exceptions import MaxTurnsExceeded
from agents.models.interface import Model
from pydantic import ValidationError

from backend.agents.research_brief import BriefStatus, ResearchBrief
from backend.agents.researcher.agent import ResearcherOutcome, run_researcher
from backend.agents.researcher_findings import SourceGroup
from backend.application.request_state import RequestState
from backend.application.structured_run import BudgetExceeded
from backend.application.tool_call_record import ToolCallOutcome

LEAD_AGENT_NAME: str = "lead"


def build_failure_reply(reason: str) -> str:
    """
    Encode a failed research call as JSON the Lead can read.
    """
    return json.dumps({"status": "failed", "reason": reason})


def check_brief(
    state: RequestState,
    event: str,
    start_date: str,
    end_date: str,
) -> tuple[tuple[date, date] | None, str | None]:
    """
    Validate the brief, fixing the window on the first call and keeping it after.
    """
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
    window: tuple[date, date] = (brief.start_date, brief.end_date)
    if state.window is None:
        state.window = window
        state.brief = brief
    elif state.window != window:
        return None, "The event window is fixed after the first research call."
    return window, None


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
    """
    Run one Researcher round for a group and return findings or a failure as JSON.
    """
    tool_name: str = f"research_{group.value}_coverage"
    window, problem = check_brief(state, event, start_date, end_date)
    if problem is None and not state.try_start_round(group):
        problem = "The research-round limit for this group has been reached."
    outcome: ResearcherOutcome | None = None
    if problem is None and window is not None:
        try:
            outcome = await run_researcher(
                state, group, window, event, focus_question, model, model_settings
            )
        except BudgetExceeded:
            problem = "The research limit was reached before this group finished."
        except MaxTurnsExceeded:
            problem = "The researcher ran out of steps before finishing."
    if outcome is not None:
        problem = outcome.failure
    if problem is not None or outcome is None or outcome.findings is None:
        state.recorder.record(
            LEAD_AGENT_NAME, tool_name, ToolCallOutcome.FAILURE, problem
        )
        return build_failure_reply(problem or "No findings were produced.")
    state.findings[group].append(outcome.findings)
    state.store.save_research(
        state.conversation_id,
        state.brief,  # type: ignore[arg-type]
        tuple(item for items in state.findings.values() for item in items),
    )
    state.recorder.record(LEAD_AGENT_NAME, tool_name, ToolCallOutcome.SUCCESS)
    return json.dumps(
        {"status": "ok", "findings": outcome.findings.model_dump(mode="json")}
    )


def build_research_tool(
    state: RequestState,
    group: SourceGroup,
    model: Model,
    model_settings: ModelSettings | None,
) -> FunctionTool:
    """
    Build the Lead's research tool for one group.
    """

    async def run(
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
            focus_question: A neutral follow-up question, or null for a broad pass.
        """
        return await research_group(
            state,
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
        name_override=f"research_{group.value}_coverage",
        description_override=(
            f"Run a fresh {group.value} researcher over its assigned outlets "
            "and return validated findings."
        ),
    )
