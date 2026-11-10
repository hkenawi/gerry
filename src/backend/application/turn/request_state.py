"""
Trusted per-request state shared by the Lead, Researchers, and Writer.

This object is passed as the agents' run context. Models never see or edit it:
the budget, conversation identity, event window, and evidence logs all live here
so limits are enforced by code rather than by prompts."""

import time
import asyncio

from uuid import UUID
from datetime import date
from typing import Callable, Protocol
from dataclasses import field, dataclass

from backend.application.settings import Settings
from backend.sources.articles import ArticleRecord
from backend.agents.research_brief import ResearchBrief
from backend.infrastructure.persistence import InMemoryStore
from backend.application.turn.request_budget import RequestBudget
from backend.agents.researcher_findings import SourceGroup, ResearcherFindings
from backend.application.turn.tool_calls import ToolCallRecord, ToolCallRecorder
from backend.sources.access import (
    ArticleReadResult,
    ArticleSearchResult,
    SourceAccessOutcome,
)


class SourceGateway(Protocol):
    """
    The source operations the agent layer is allowed to call.
    """

    def search_articles(
        self,
        query: str,
        start_date: date,
        end_date: date,
        assigned_outlets: tuple[str, ...],
    ) -> ArticleSearchResult:
        """
        Discover candidate articles without collecting evidence.
        """

    def read_article(
        self,
        url: str,
        outlet_id: str,
        conversation_id: str,
        start_date: date,
        end_date: date,
        assigned_outlets: tuple[str, ...],
    ) -> ArticleReadResult:
        """
        Extract and save one article, or return an explicit failure.
        """

    def read_collected_article(
        self,
        conversation_id: str,
        article_id: UUID,
    ) -> ArticleRecord:
        """
        Read already saved evidence only.
        """


@dataclass
class RequestState:
    """
    Everything trusted that one request needs, created fresh for each request.
    """

    conversation_id: str
    settings: Settings
    budget: RequestBudget
    store: InMemoryStore
    sources: SourceGateway
    recorder: ToolCallRecorder
    failed_reads: list[SourceAccessOutcome] = field(default_factory=list)
    brief: ResearchBrief | None = None
    final_answer: str | None = None
    writer_calls: int = 0
    reusing_research: bool = False
    research_slots: asyncio.Semaphore = field(init=False)
    findings: dict[SourceGroup, list[ResearcherFindings]] = field(
        default_factory=lambda: {group: [] for group in SourceGroup}
    )
    rounds_started: dict[SourceGroup, int] = field(
        default_factory=lambda: {group: 0 for group in SourceGroup}
    )

    def __post_init__(self) -> None:
        """Limit simultaneous Researcher runs for this request."""
        self.research_slots = asyncio.Semaphore(self.settings.max_concurrent_researchers)

    def try_start_round(self, group: SourceGroup) -> bool:
        """
        Start one research round for a group unless its round ceiling is reached.
        """
        if self.rounds_started[group] >= self.settings.max_research_rounds:
            return False
        self.rounds_started[group] += 1
        return True


def build_request_state(
    conversation_id: str,
    settings: Settings,
    store: InMemoryStore,
    sources: SourceGateway,
    clock: Callable[[], float] = time.monotonic,
    *,
    on_tool_record: Callable[[ToolCallRecord], None] | None = None,
) -> RequestState:
    """
    Create request state with a fresh budget and an empty tool-call recorder.
    """
    state: RequestState = RequestState(
        conversation_id=conversation_id,
        settings=settings,
        budget=RequestBudget(settings, clock=clock),
        store=store,
        sources=sources,
        recorder=ToolCallRecorder(on_tool_record),
    )
    brief: ResearchBrief
    findings: tuple[ResearcherFindings, ...]
    try:
        brief, findings = store.load_research(conversation_id)
    except KeyError:
        return state
    if brief.start_date is not None and brief.end_date is not None:
        state.reusing_research = True
        state.brief = brief
        for item in findings:
            state.findings[item.group].append(item)
    return state
