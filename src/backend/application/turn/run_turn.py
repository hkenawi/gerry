"""
Run one turn of the Lead, Researcher, and Writer workflow.

``run_turn`` is a plain async function with no HTTP dependency. It clarifies an
unclear request, researches both source groups concurrently, decides in code
whether the evidence supports a comparison or only a summary, has the Writer
produce cited claims, and renders the validated answer. The HTTP layer, sessions,
and progress streaming are connected to this function separately."""

import re
import asyncio
import logging

from openai import APIError
from datetime import date
from dataclasses import dataclass
from agents.models.interface import Model
from agents.exceptions import MaxTurnsExceeded
from agents import Agent, ModelSettings, TResponseInputItem

from backend.sources.articles import ArticleRecord
from backend.agents.lead.schemas import LeadOutcome
from backend.agents.lead.tools import find_events
from backend.agents.research_brief import BriefStatus
from backend.agents.lead.agent import build_lead_agent
from backend.agents.researcher_findings import SourceGroup
from backend.agents.writer.schemas import Claim, WriterReport
from backend.application.turn.request_state import RequestState
from backend.interfaces.http.chat_contracts import ChatMessage, ChatRole
from backend.application.answer.answer_rendering import render_answer, render_event_options
from backend.application.evidence.outlet_assignments import outlet_display_name
from backend.application.turn.tool_calls import ToolCallOutcome, ToolCallRecord
from backend.application.evidence.recent_events import RECENT_TIME_PHRASE
from backend.application.evidence.collected_evidence import collect_articles_by_group
from backend.application.turn.failure_category import FailureCategory, describe_failure
from backend.application.turn.structured_run import BudgetExceeded, run_with_correction
from backend.application.answer.sample_assessment import (
    AnswerMode,
    SampleAssessment,
    assess_sample,
)

logger: logging.Logger = logging.getLogger(__name__)
LIMIT_NOTE: str = (
    "The research limit was reached before every gap could be followed up, "
    "so some gaps remain."
)
RECENT_PLACE_QUESTION: re.Pattern[str] = re.compile(
    r"(?:tell me(?: about)?\s+)?"
    r"(?:what(?:['’]?s| is)\s+(?:going on|happening|the latest)"
    r"|(?:any|latest|recent)\s+(?:news|headlines))"
    r"\s+(?:in|from|around|with)\s+(?P<topic>.+?)"
    rf"(?:\s+{RECENT_TIME_PHRASE})?[?!.]*",
    re.IGNORECASE,
)
DIRECT_RESEARCH_REQUEST: re.Pattern[str] = re.compile(
    r"^(?:please\s+)?(?:tell me about|explain|summari[sz]e|brief me on"
    r"|compare (?:the )?coverage of|how did (?:(?:the|different) )?(?:outlets|press|media) cover)\s+"
    r"(?!(?:the\s+)?(?:(?:latest|recent|current)\s+)?(?:events|headlines|news|stories)\b|what\b)",
    re.IGNORECASE,
)
EXPLICIT_DATE_IN_TOPIC: re.Pattern[str] = re.compile(
    r"\b(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2})\b"
    r"|\s(?:from|between|on|since)\s+(?:[a-z]+\.?\s+)?\d",
    re.IGNORECASE,
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
    question: str = " ".join(messages[-1].content.split())
    agent: Agent[RequestState] = build_lead_agent(
        state, model, model_settings, today,
        allow_event_discovery=DIRECT_RESEARCH_REQUEST.match(question) is None,
    )

    def validate(output: LeadOutcome) -> str | None:
        """
        Require research and a stored answer before a clear brief is accepted.
        """
        if output.event_ids:
            if output.brief.status is BriefStatus.CLEAR:
                return "Offer events only with a needs_clarification brief."
            unknown: list[int] = [i for i in output.event_ids if i not in state.event_options]
            return f"Event IDs {unknown} were not in the search results." if unknown else None
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
    current_date: date = today or date.today()
    state.previous_answers = tuple(
        message.content for message in messages if message.role is ChatRole.ASSISTANT
    )
    try:
        discovery: re.Match[str] | None = RECENT_PLACE_QUESTION.fullmatch(
            messages[-1].content.strip(),
        )
        topic: str | None = discovery.group("topic") if discovery is not None else None
        if topic and not EXPLICIT_DATE_IN_TOPIC.search(topic):
            await asyncio.wait_for(
                find_events(state, topic, None, None, today=current_date),
                timeout=state.budget.remaining_seconds(),
            )
            answer: str = "Recent headlines could not be loaded. Please try again shortly."
            if state.events_window is not None:
                answer = render_event_options(
                    list(state.event_options.values()),
                    state.events_window,
                )
            return TurnResult(answer, state.recorder.records)
        outcome: LeadOutcome | None = await run_lead_stage(
            state, model, model_settings, messages, current_date,
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
    except APIError as error:
        logger.error("Model provider failed during the Lead stage (%s).", type(error).__name__)
        state.recorder.record(
            "lead", "research", ToolCallOutcome.FAILURE, "The language model was unavailable.",
        )
        if state.final_answer is not None:
            return TurnResult(state.final_answer, state.recorder.records)
        return build_failure_result(state, FailureCategory.MODEL_UNAVAILABLE)
    if outcome is None:
        return build_failure_result(state, FailureCategory.INVALID_OUTPUT)
    if outcome.brief.status is not BriefStatus.CLEAR:
        question: str = outcome.brief.clarifying_question or ""
        if state.events_window is not None:
            question = render_event_options(
                [state.event_options[i] for i in dict.fromkeys(outcome.event_ids)],
                state.events_window,
            )
        return TurnResult(question, state.recorder.records)
    if state.final_answer is None:
        return build_failure_result(state, FailureCategory.INVALID_OUTPUT)
    return TurnResult(state.final_answer, state.recorder.records)
