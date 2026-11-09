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
from backend.agents.lead.schemas import AspectAlignment, LeadOutcome
from backend.agents.research_brief import BriefStatus
from backend.agents.researcher_findings import SourceGroup
from backend.agents.writer.agent import (
    WRITER_MAX_TURNS,
    build_writer_agent,
    build_writer_input,
)
from backend.agents.writer.schemas import WriterReport
from backend.application.answer_rendering import (
    find_alignment_problems,
    find_report_problems,
    render_answer,
    render_no_evidence_answer,
)
from backend.application.failure_category import FailureCategory, describe_failure
from backend.application.request_state import RequestState
from backend.application.sample_assessment import (
    AnswerMode,
    SampleAssessment,
    assess_sample,
)
from backend.application.structured_run import BudgetExceeded, run_with_correction
from backend.application.tool_call_record import ToolCallOutcome, ToolCallRecord
from backend.interfaces.http.chat_contracts import ChatMessage
from backend.sources.articles import ArticleRecord

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


def collect_articles_by_group(
    state: RequestState,
) -> dict[SourceGroup, tuple[ArticleRecord, ...]]:
    """
    Gather the saved articles each group's Researchers reported reading.
    """
    saved: dict[str, ArticleRecord] = {
        str(article.article_id): article
        for article in state.store.list_articles(state.conversation_id)
    }
    return {
        group: tuple(
            saved[article_id]
            for article_id in dict.fromkeys(
                article_id
                for findings in state.findings[group]
                for article_id in findings.article_ids
            )
            if article_id in saved
        )
        for group in SourceGroup
    }


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
        Require research before a clear brief and a group-correct alignment.
        """
        if output.brief.status is not BriefStatus.CLEAR:
            return None
        if state.brief is None:
            return "Run research with both research tools before finishing."
        problems: list[str] = find_alignment_problems(
            output.alignment, collect_articles_by_group(state)
        )
        return " ".join(problems) or None

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
            timeout=state.settings.request_deadline_seconds * RESEARCH_TIME_SHARE,
        )
    except (BudgetExceeded, MaxTurnsExceeded, TimeoutError):
        return None, None, True
    return output, problem, False


async def run_writer_stage(
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None,
    assessment: SampleAssessment,
    alignment: list[AspectAlignment],
    articles_by_group: dict[SourceGroup, tuple[ArticleRecord, ...]],
) -> WriterReport | None:
    """
    Run the Writer with one correction attempt, returning a valid report or None.
    """
    articles: tuple[ArticleRecord, ...] = tuple(
        article for group in SourceGroup for article in articles_by_group[group]
    )
    assert state.brief is not None

    def validate(report: WriterReport) -> str | None:
        """
        Reject reports citing unknown passages or breaking the answer mode.
        """
        return " ".join(
            find_report_problems(report, alignment, articles, assessment)
        ) or None

    remaining: float = state.settings.request_deadline_seconds * (
        1 - RESEARCH_TIME_SHARE
    )
    try:
        report, _ = await asyncio.wait_for(
            run_with_correction(
                build_writer_agent(model, model_settings),
                [
                    {
                        "role": "user",
                        "content": build_writer_input(
                            state.brief,
                            assessment,
                            alignment,
                            [
                                item
                                for items in state.findings.values()
                                for item in items
                            ],
                            articles,
                        ),
                    }
                ],
                state,
                validate,
                WRITER_MAX_TURNS,
                enforce_budget=False,
            ),
            timeout=remaining,
        )
    except (MaxTurnsExceeded, TimeoutError):
        return None
    return report


async def run_turn(
    messages: list[ChatMessage],
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None = None,
    today: date | None = None,
) -> TurnResult:
    """
    Answer one turn: clarify, research both groups, then write a cited answer.
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
    articles_by_group: dict[SourceGroup, tuple[ArticleRecord, ...]] = (
        collect_articles_by_group(state)
    )
    assessment: SampleAssessment = assess_sample(articles_by_group)
    if limit_hit and assessment.mode is AnswerMode.NO_EVIDENCE:
        return build_failure_result(state, FailureCategory.RESEARCH_LIMIT_REACHED)
    if assessment.mode is AnswerMode.NO_EVIDENCE:
        return TurnResult(
            render_no_evidence_answer(assessment.reason, state.failed_reads),
            state.recorder.records,
        )
    alignment: list[AspectAlignment] = outcome.alignment if outcome else []
    report: WriterReport | None = await run_writer_stage(
        state, model, model_settings, assessment, alignment, articles_by_group
    )
    if report is None:
        return build_failure_result(state, FailureCategory.INVALID_OUTPUT)
    articles: tuple[ArticleRecord, ...] = tuple(
        article for group in SourceGroup for article in articles_by_group[group]
    )
    return TurnResult(
        render_answer(
            report,
            alignment,
            assessment,
            articles,
            state.failed_reads,
            notes=(LIMIT_NOTE,) if limit_hit else (),
        ),
        state.recorder.records,
    )
