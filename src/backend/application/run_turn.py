"""
Run one turn of the Lead, Researcher, and Writer workflow.

``run_turn`` is a plain async function with no HTTP dependency. It clarifies an
unclear request, researches both source groups concurrently, decides in code
whether the evidence supports a comparison or only a summary, has the Writer
produce cited claims, and renders the validated answer. The HTTP layer, sessions,
and progress streaming are connected to this function separately.
"""

import asyncio
from datetime import date
from dataclasses import dataclass

from agents import Agent, ModelSettings
from agents.exceptions import MaxTurnsExceeded
from agents.models.interface import Model

from backend.agents.lead.agent import build_lead_agent
from backend.agents.lead.schemas import LeadOutcome
from backend.agents.research_brief import BriefStatus
from backend.application.failure_category import FailureCategory, describe_failure
from backend.application.collected_evidence import collect_articles_by_group
from backend.application.request_state import RequestState
from backend.application.sample_assessment import AnswerMode, assess_sample
from backend.application.structured_run import BudgetExceeded, run_with_correction
from backend.application.tool_call_record import ToolCallOutcome, ToolCallRecord
from backend.application.write_answer import write_answer
from backend.interfaces.http.chat_contracts import ChatMessage

RESEARCH_TIME_SHARE: float = 0.7
LIMIT_NOTE: str = (
    "The research limit was reached before every gap could be followed up, "
    "so some gaps remain."
)


@dataclass(frozen=True)
class TurnResult:
    """
    The reader-facing answer, the recorded tool calls, and any failure category.
    """

    answer: str
    tool_calls: tuple[ToolCallRecord, ...]
    failure: FailureCategory | None = None


def build_failure_result(
    state: RequestState,
    category: FailureCategory,
) -> TurnResult:
    """
    Build the plain-language result for a failed stage.
    """
    return TurnResult(
        describe_failure(category).message,
        state.recorder.records,
        category,
    )


async def run_lead_stage(
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None,
    messages: list[ChatMessage],
    today: date,
) -> tuple[LeadOutcome | None, str | None, bool]:
    """
    Run the Lead, returning its outcome, any unresolved problem, and a limit flag.
    """
    agent: Agent[RequestState] = build_lead_agent(state, model, model_settings, today)

    def validate(output: LeadOutcome) -> str | None:
        """
        Require research and a stored answer before a clear brief is accepted.
        """
        if output.brief.status is not BriefStatus.CLEAR:
            return None
        if state.brief is None:
            return "Run research with both research tools before finishing."
        if state.final_answer is None:
            return "Call write_answer successfully before finishing."
        return None

    try:
        output, problem = await asyncio.wait_for(
            run_with_correction(
                agent,
                [
                    {"role": message.role.value, "content": message.content}
                    for message in messages
                ],
                state,
                validate,
                state.settings.max_lead_turns,
            ),
            timeout=state.settings.request_deadline_seconds,
        )
    except (BudgetExceeded, MaxTurnsExceeded, TimeoutError):
        return None, None, True
    return output, problem, False


async def run_fallback_writer(
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None,
) -> None:
    """
    Write from the evidence already collected after the Lead hit a limit.

    The alignment is left empty because the Lead could not supply one.
    """
    assert state.brief is not None
    try:
        await asyncio.wait_for(
            write_answer(
                state,
                model,
                model_settings,
                state.brief.event,
                [],
                notes=(LIMIT_NOTE,),
                enforce_cap=False,
            ),
            timeout=state.settings.request_deadline_seconds
            * (1 - RESEARCH_TIME_SHARE),
        )
    except (MaxTurnsExceeded, TimeoutError):
        return


async def run_turn(
    messages: list[ChatMessage],
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None = None,
    today: date | None = None,
) -> TurnResult:
    """
    Answer one turn: clarify, or research both groups and let the Lead call the Writer.
    """
    outcome, problem, limit_hit = await run_lead_stage(
        state, model, model_settings, messages, today or date.today()
    )
    if limit_hit:
        state.recorder.record(
            "lead",
            "research",
            ToolCallOutcome.FAILURE,
            "The research limit was reached.",
        )
    elif outcome is None:
        return build_failure_result(state, FailureCategory.INVALID_OUTPUT)
    elif outcome.brief.status is not BriefStatus.CLEAR:
        return TurnResult(
            outcome.brief.clarifying_question or "",
            state.recorder.records,
        )
    if state.final_answer is None and limit_hit and state.brief is not None:
        assessment = assess_sample(collect_articles_by_group(state))
        if assessment.mode is AnswerMode.NO_EVIDENCE:
            return build_failure_result(state, FailureCategory.RESEARCH_LIMIT_REACHED)
        await run_fallback_writer(state, model, model_settings)
    if state.final_answer is None:
        category: FailureCategory = (
            FailureCategory.RESEARCH_LIMIT_REACHED
            if limit_hit
            else FailureCategory.INVALID_OUTPUT
        )
        return build_failure_result(state, category)
    return TurnResult(state.final_answer, state.recorder.records)
