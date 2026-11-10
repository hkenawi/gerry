"""
The Writer agent: produces cited claims from already-collected evidence.

The Lead calls the Writer through its ``write_answer`` tool once research ends.
The Writer cannot browse; its only tool re-reads
articles already saved for the conversation. Application code renders the final
answer from its claims and verifies every citation.
"""

import json

from uuid import UUID
from pathlib import Path
from agents.models.interface import Model
from agents import Agent, ModelSettings, RunContextWrapper, function_tool

from backend.sources.articles import ArticleRecord
from backend.agents.writer.schemas import WriterReport
from backend.agents.lead.schemas import AspectAlignment
from backend.agents.research_brief import ResearchBrief
from backend.application.turn.request_state import RequestState
from backend.application.turn.tool_calls import ToolCallOutcome
from backend.agents.researcher_findings import ResearcherFindings
from backend.application.answer.sample_assessment import SampleAssessment

PROMPT: str = Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")
WRITER_AGENT_NAME: str = "writer"
WRITER_MAX_TURNS: int = 4


@function_tool
async def read_collected_article(
    context: RunContextWrapper[RequestState],
    article_id: str,
) -> str:
    """
    Re-read an article that was already collected in this conversation.

    Args:
        article_id: The article ID from the evidence.
    """
    state: RequestState = context.context
    try:
        article: ArticleRecord = state.sources.read_collected_article(
            state.conversation_id, UUID(article_id)
        )
    except (KeyError, ValueError):
        state.recorder.record(
            WRITER_AGENT_NAME,
            "read_collected_article",
            ToolCallOutcome.FAILURE,
            "That article was not collected in this conversation.",
        )
        return "That article was not collected in this conversation."
    state.recorder.record(
        WRITER_AGENT_NAME, "read_collected_article", ToolCallOutcome.SUCCESS
    )
    return article.model_dump_json()


def build_writer_agent(
    model: Model,
    model_settings: ModelSettings | None,
) -> Agent[RequestState]:
    """
    Build the Writer with read-only access to collected articles.
    """
    return Agent(
        name=WRITER_AGENT_NAME,
        instructions=PROMPT,
        model=model,
        model_settings=model_settings or ModelSettings(),
        tools=[read_collected_article],
        output_type=WriterReport,
    )


def describe_evidence(articles: tuple[ArticleRecord, ...]) -> str:
    """
    List each collected article with its passages, labelled by their IDs.
    """
    blocks: list[str] = []
    for article in articles:
        passages: str = "\n".join(
            f"{passage.passage_id}: {passage.text}" for passage in article.passages
        )
        blocks.append(
            f"Article {article.article_id} ({article.outlet_id}, "
            f"{article.article_type.value}): {article.title}\n{passages}"
        )
    return "\n\n".join(blocks)


def build_writer_input(
    question: str,
    brief: ResearchBrief,
    assessment: SampleAssessment,
    alignment: list[AspectAlignment],
    findings: list[ResearcherFindings],
    articles: tuple[ArticleRecord, ...],
) -> str:
    """
    Assemble the evidence package the Writer works from.
    """
    return (
        f"Reader's question: {question}\n"
        f"Event: {brief.event}\n"
        f"Answer mode: {assessment.mode.value}\n"
        f"Mode reason: {assessment.reason or 'none'}\n"
        f"Sample: {assessment.sample_statement}\n\n"
        "Aspect alignment:\n"
        + json.dumps([row.model_dump(mode="json") for row in alignment])
        + "\n\nResearcher findings:\n"
        + json.dumps([item.model_dump(mode="json") for item in findings])
        + "\n\nCollected articles:\n"
        + describe_evidence(articles)
    )
