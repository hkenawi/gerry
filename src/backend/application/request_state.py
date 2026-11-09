"""
Trusted per-request state shared by the Lead, Researchers, and Writer.

This object is passed as the agents' run context. Models never see or edit it:
the budget, conversation identity, event window, and evidence logs all live here
so limits are enforced by code rather than by prompts.
"""

import time
from uuid import UUID
from datetime import date
from typing import Callable, Protocol
from dataclasses import field, dataclass

from backend.sources.articles import ArticleRecord
from backend.application.settings import Settings
from backend.infrastructure.persistence import InMemoryStore
from backend.application.request_budget import RequestBudget
from backend.agents.research_brief import ResearchBrief
from backend.agents.researcher_findings import SourceGroup, ResearcherFindings
from backend.application.tool_call_recorder import ToolCallRecorder
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
    window: tuple[date, date] | None = None
    brief: ResearchBrief | None = None
    findings: dict[SourceGroup, list[ResearcherFindings]] = field(
        default_factory=lambda: {group: [] for group in SourceGroup}
    )
    rounds_started: dict[SourceGroup, int] = field(
        default_factory=lambda: {group: 0 for group in SourceGroup}
    )

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
) -> RequestState:
    """
    Create request state with a fresh budget and an empty tool-call recorder.
    """
    return RequestState(
        conversation_id=conversation_id,
        settings=settings,
        budget=RequestBudget(settings, clock=clock),
        store=store,
        sources=sources,
        recorder=ToolCallRecorder(),
    )
