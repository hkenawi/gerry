"""
Produce the final cited answer: run the Writer, validate, render, and store it.

The Lead's ``write_answer`` tool delegates here to select the answer mode from
saved articles, check the Lead's alignment and the Writer's claims, and store
the rendered Markdown in the request state."""

import json
import logging

from agents import ModelSettings
from dataclasses import dataclass
from agents.models.interface import Model
from agents.exceptions import MaxTurnsExceeded

from backend.sources.articles import ArticleRecord
from backend.agents.writer.schemas import WriterReport
from backend.agents.lead.schemas import AspectAlignment
from backend.agents.researcher_findings import SourceGroup
from backend.application.turn.request_state import RequestState
from backend.application.turn.structured_run import run_with_correction
from backend.application.evidence.collected_evidence import collect_articles_by_group
from backend.agents.writer.agent import (
    WRITER_MAX_TURNS,
    build_writer_agent,
    build_writer_input,
)
from backend.application.answer.sample_assessment import (
    AnswerMode,
    SampleAssessment,
    assess_sample,
)
from backend.application.answer.answer_rendering import (
    render_answer,
    find_report_problems,
    find_alignment_problems,
    render_no_evidence_answer,
)

logger: logging.Logger = logging.getLogger(__name__)
MAX_WRITER_CALLS: int = 2


@dataclass(frozen=True)
class WriteResult:
    """
    Whether an answer was stored, and a short message for the Lead.
    """

    succeeded: bool
    message: str


def refuse(message: str) -> WriteResult:
    """
    Build a failed result the Lead can read and act on.
    """
    return WriteResult(False, json.dumps({"status": "failed", "reason": message}))


async def write_answer(
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None,
    question: str,
    alignment: list[AspectAlignment],
) -> WriteResult:
    """Write, validate, and store the answer or explain the failure."""
    if state.writer_calls >= MAX_WRITER_CALLS:
        return refuse("The Writer has already been tried the maximum number of times.")
    state.writer_calls += 1
    articles_by_group: dict[SourceGroup, tuple[ArticleRecord, ...]] = (
        collect_articles_by_group(state)
    )
    assessment: SampleAssessment = assess_sample(articles_by_group)
    if assessment.mode is AnswerMode.NO_EVIDENCE:
        state.final_answer = render_no_evidence_answer(
            assessment.reason, state.failed_reads
        )
        return WriteResult(True, json.dumps({"status": "ok", "mode": "no_evidence"}))
    if state.brief is None:
        return refuse("Research must run before the answer can be written.")
    passage_ids_by_group: dict[SourceGroup, set[str]] = {
        group: {
            passage.passage_id
            for article in group_articles
            for passage in article.passages
        }
        for group, group_articles in articles_by_group.items()
    }
    alignment_problems: list[str] = find_alignment_problems(
        alignment, passage_ids_by_group
    )
    if alignment_problems:
        return refuse(" ".join(alignment_problems))
    articles: tuple[ArticleRecord, ...] = tuple(
        article for group in SourceGroup for article in articles_by_group[group]
    )
    known_passage_ids: set[str] = set().union(*passage_ids_by_group.values())

    def validate(report: WriterReport) -> str | None:
        """Reject claims with unknown citations or outside the answer mode."""
        return " ".join(
            find_report_problems(report, known_passage_ids, assessment)
        ) or None

    writer_input: str = build_writer_input(
        question,
        state.brief,
        assessment,
        alignment,
        [item for items in state.findings.values() for item in items],
        articles,
    )
    report: WriterReport | None
    problem: str | None
    try:
        report, problem = await run_with_correction(
            build_writer_agent(model, model_settings),
            [{"role": "user", "content": writer_input}],
            state,
            validate,
            WRITER_MAX_TURNS,
        )
    except MaxTurnsExceeded:
        return refuse("The Writer ran out of steps before finishing.")
    except Exception as error:
        logger.error("The Writer failed (%s).", type(error).__name__)
        return refuse("The Writer could not finish because of an error.")
    if report is None:
        return refuse(problem or "The Writer could not produce a valid answer.")
    if report.evidence_gap:
        return refuse(f"The Writer needs more evidence. {report.evidence_gap}")
    state.final_answer = render_answer(
        report,
        alignment,
        assessment,
        articles,
        state.failed_reads,
    )
    return WriteResult(
        True,
        json.dumps({"status": "ok", "mode": assessment.mode.value}),
    )
