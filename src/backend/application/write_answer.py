"""
Produce the final cited answer: run the Writer, validate, render, and store it.

This is the code behind the Lead's ``write_answer`` tool. Code decides the
answer mode from the saved articles, validates the
alignment and the Writer's claims, renders the Markdown, and stores the result in
the request state. The Lead never sees or edits the rendered text.
"""

import json
from dataclasses import dataclass

from agents import ModelSettings
from agents.exceptions import MaxTurnsExceeded
from agents.models.interface import Model

from backend.agents.lead.schemas import AspectAlignment
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
from backend.application.collected_evidence import collect_articles_by_group
from backend.application.request_state import RequestState
from backend.application.sample_assessment import (
    AnswerMode,
    SampleAssessment,
    assess_sample,
)
from backend.application.structured_run import run_with_correction
from backend.agents.researcher_findings import SourceGroup
from backend.sources.articles import ArticleRecord

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
    notes: tuple[str, ...] = (),
) -> WriteResult:
    """
    Write, validate, render, and store the answer, or explain why it cannot be.
    """
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
    alignment_problems: list[str] = find_alignment_problems(
        alignment, articles_by_group
    )
    if alignment_problems:
        return refuse(" ".join(alignment_problems))
    articles: tuple[ArticleRecord, ...] = tuple(
        article for group in SourceGroup for article in articles_by_group[group]
    )

    def validate(report: WriterReport) -> str | None:
        """
        Reject reports citing unknown passages or breaking the answer mode.
        """
        return " ".join(
            find_report_problems(report, alignment, articles, assessment)
        ) or None

    try:
        report, problem = await run_with_correction(
            build_writer_agent(model, model_settings),
            [
                {
                    "role": "user",
                    "content": build_writer_input(
                        question,
                        state.brief,
                        assessment,
                        alignment,
                        [item for items in state.findings.values() for item in items],
                        articles,
                    ),
                }
            ],
            state,
            validate,
            WRITER_MAX_TURNS,
        )
    except MaxTurnsExceeded:
        return refuse("The Writer ran out of steps before finishing.")
    if report is None:
        return refuse(problem or "The Writer could not produce a valid answer.")
    if report.evidence_gap:
        return refuse(f"The Writer needs more evidence. {report.evidence_gap}")
    state.final_answer = render_answer(
        report, alignment, assessment, articles, state.failed_reads, notes
    )
    return WriteResult(True, json.dumps({"status": "ok", "mode": assessment.mode.value}))
