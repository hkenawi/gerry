"""
Run one turn of the Lead, Researcher, and Writer workflow.

``run_turn`` is a plain async function with no HTTP dependency. It clarifies an
unclear request, researches both source groups concurrently, decides in code
whether the evidence supports a comparison or only a summary, has the Writer
produce cited claims, and renders the validated answer. The HTTP layer, sessions,
and progress streaming are connected to this function separately."""

import asyncio

from datetime import date
from dataclasses import dataclass
from agents.models.interface import Model
from agents.exceptions import MaxTurnsExceeded
from agents import Agent, ModelSettings, TResponseInputItem

from backend.sources.articles import ArticleRecord
from backend.agents.lead.schemas import LeadOutcome
from backend.agents.research_brief import BriefStatus
from backend.agents.lead.agent import build_lead_agent
from backend.agents.researcher_findings import SourceGroup
from backend.agents.writer.schemas import Claim, WriterReport
from backend.interfaces.http.chat_contracts import ChatMessage
from backend.application.turn.request_state import RequestState
from backend.application.answer.answer_rendering import render_answer
from backend.application.evidence.outlet_assignments import outlet_display_name
from backend.application.turn.tool_calls import ToolCallOutcome, ToolCallRecord
from backend.application.evidence.collected_evidence import collect_articles_by_group
from backend.application.turn.failure_category import FailureCategory, describe_failure
from backend.application.turn.structured_run import BudgetExceeded, run_with_correction
from backend.application.answer.sample_assessment import (
    AnswerMode,
    SampleAssessment,
    assess_sample,
)

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
) -> LeadOutcome | None:
    """Run the Lead within the remaining deadline and return its validated outcome."""
    agent: Agent[RequestState] = build_lead_agent(state, model, model_settings, today)

    def validate(output: LeadOutcome) -> str | None:
        """
        Require research and a stored answer before a clear brief is accepted.
        """
        if output.brief.status is not BriefStatus.CLEAR:
            return None
        if state.brief is None:
            return "Run research with both research tools before finishing."
        if output.brief != state.brief:
            return "Finish with the same event and publication window used for research."
        if state.final_answer is None:
            return "Call write_answer successfully before finishing."
        return None

    items: list[TResponseInputItem] = [
        {"role": message.role.value, "content": message.content}
        for message in messages
    ]
    output: LeadOutcome | None
    output, _ = await asyncio.wait_for(
        run_with_correction(agent, items, state, validate, state.settings.max_lead_turns),
        timeout=state.budget.remaining_seconds(),
    )
    return output


def render_limited_answer(state: RequestState) -> str | None:
    """List verified article headlines and citations after a request limit."""
    groups: dict[SourceGroup, tuple[ArticleRecord, ...]] = collect_articles_by_group(state)
    assessment: SampleAssessment = assess_sample(groups)
    if assessment.mode is AnswerMode.NO_EVIDENCE:
        return None
    articles: tuple[ArticleRecord, ...] = tuple(
        article for group_articles in groups.values() for article in group_articles
    )
    report: WriterReport = WriterReport(
        summary=[
            Claim(
                text=f"{outlet_display_name(article.outlet_id)} published “{article.title}”.",
                passage_ids=[article.passages[0].passage_id],
            )
            for article in articles
        ],
    )
    return render_answer(
        report,
        [],
        assessment,
        articles,
        state.failed_reads,
        (LIMIT_NOTE, "This partial result lists the available headlines."),
    )


async def run_turn(
    messages: list[ChatMessage],
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None = None,
    today: date | None = None,
) -> TurnResult:
    """Clarify the request or coordinate both research groups and the Writer."""
    try:
        outcome: LeadOutcome | None = await run_lead_stage(
            state, model, model_settings, messages, today or date.today(),
        )
    except (BudgetExceeded, MaxTurnsExceeded, TimeoutError):
        state.recorder.record(
            "lead",
            "research",
            ToolCallOutcome.FAILURE,
            "The research limit was reached.",
        )
        if state.final_answer is None:
            state.final_answer = render_limited_answer(state)
        if state.final_answer is None:
            return build_failure_result(state, FailureCategory.RESEARCH_LIMIT_REACHED)
        return TurnResult(state.final_answer, state.recorder.records)
    if outcome is None:
        return build_failure_result(state, FailureCategory.INVALID_OUTPUT)
    if outcome.brief.status is not BriefStatus.CLEAR:
        return TurnResult(
            outcome.brief.clarifying_question or "",
            state.recorder.records,
        )
    if state.final_answer is None:
        return build_failure_result(state, FailureCategory.INVALID_OUTPUT)
    return TurnResult(state.final_answer, state.recorder.records)
