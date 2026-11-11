"""
Trusted source tools for one Researcher run.

The model supplies only a search query or an article URL. Everything that limits
what may be fetched, namely the group's outlets, the date window, the shared
budget, and retries, is bound here in code and cannot be widened by the model.
Blocking source calls run in worker threads so concurrent researchers overlap."""

import asyncio

from datetime import date

from backend.sources.constants import SourceAccessStatus
from backend.agents.researcher_findings import SourceGroup
from backend.application.turn.request_state import RequestState
from backend.application.turn.tool_calls import ToolCallOutcome
from backend.application.turn.request_budget import BudgetResource
from backend.application.evidence.outlet_assignments import outlets_for_group
from backend.sources.access import (
    ArticleReadResult,
    ArticleSearchResult,
    SourceAccessOutcome,
)


class GroupSourceTools:
    """
    Search and read tools restricted to one group's outlets and one date window.
    """

    def __init__(
        self,
        state: RequestState,
        group: SourceGroup,
        window: tuple[date, date],
    ) -> None:
        """
        Bind the tools to their trusted group, window, and shared request state.
        """
        self._state: RequestState = state
        self._window: tuple[date, date] = window
        self._outlets: tuple[str, ...] = outlets_for_group(group)
        self._agent: str = f"researcher_{group.value}"

    async def search_articles(self, query: str) -> ArticleSearchResult:
        """Discover candidate articles for the assigned outlets and window."""
        result: ArticleSearchResult
        if self._state.budget.try_consume(BudgetResource.SEARCH_CALLS):
            try:
                result = await asyncio.to_thread(
                    self._state.sources.search_articles,
                    query,
                    self._window[0],
                    self._window[1],
                    self._outlets,
                )
            except ValueError:
                result = self._build_search_failure(
                    SourceAccessStatus.FETCH_FAILED,
                    "The search request was not valid.",
                )
        else:
            result = self._build_search_failure(
                SourceAccessStatus.BUDGET_EXHAUSTED,
                "The search budget for this request is used up.",
            )
        self._record_search(query, result)
        return result

    def _build_search_failure(
        self,
        status: SourceAccessStatus,
        detail: str,
    ) -> ArticleSearchResult:
        """Report the same failure for each outlet in the search assignment."""
        return ArticleSearchResult(
            outcomes=tuple(
                SourceAccessOutcome(outlet_id=outlet, status=status, detail=detail)
                for outlet in self._outlets
            ),
        )

    async def read_article(self, url: str, outlet_id: str) -> ArticleReadResult:
        """
        Read and save one article, retrying only transient fetch failures.
        """
        if outlet_id not in self._outlets:
            return self._finish_read(
                ArticleReadResult(
                    outcome=SourceAccessOutcome(
                        outlet_id=outlet_id,
                        status=SourceAccessStatus.ACCESS_DENIED,
                        url=url,
                        detail="This outlet is not assigned to this researcher.",
                    )
                ),
                url,
                outlet_id,
            )
        result: ArticleReadResult | None = None
        for _ in range(self._state.settings.max_retries + 1):
            if not self._state.budget.try_consume(BudgetResource.ARTICLE_READS):
                result = ArticleReadResult(
                    outcome=SourceAccessOutcome(
                        outlet_id=outlet_id,
                        status=SourceAccessStatus.BUDGET_EXHAUSTED,
                        url=url,
                        detail="The article-read budget for this request is used up.",
                    )
                )
                break
            result = await asyncio.to_thread(
                self._state.sources.read_article,
                url,
                outlet_id,
                self._state.conversation_id,
                self._window[0],
                self._window[1],
                self._outlets,
            )
            if result.outcome.status is not SourceAccessStatus.FETCH_FAILED:
                break
        assert result is not None
        return self._finish_read(result, url, outlet_id)

    def _finish_read(
        self, result: ArticleReadResult, url: str, outlet_id: str,
    ) -> ArticleReadResult:
        """
        Record the final read outcome and remember failures for the answer.
        """
        succeeded: bool = result.outcome.status is SourceAccessStatus.SUCCESS
        if not succeeded:
            self._state.failed_reads.append(result.outcome)
        self._state.recorder.record(
            self._agent,
            "read_article",
            ToolCallOutcome.SUCCESS if succeeded else ToolCallOutcome.FAILURE,
            None if succeeded else self._describe(result.outcome),
            args={"url": url, "outlet_id": outlet_id},
            result=result.model_dump_json(),
        )
        return result

    def _record_search(self, query: str, result: ArticleSearchResult) -> None:
        """
        Record a search as successful when at least one outlet answered.
        """
        succeeded: bool = any(
            outcome.status is SourceAccessStatus.SUCCESS
            or outcome.status is SourceAccessStatus.NO_RESULTS
            for outcome in result.outcomes
        )
        self._state.recorder.record(
            self._agent,
            "search_articles",
            ToolCallOutcome.SUCCESS if succeeded else ToolCallOutcome.FAILURE,
            None if succeeded else "No outlet could be searched.",
            args={"query": query},
            result=result.model_dump_json(),
        )

    @staticmethod
    def _describe(outcome: SourceAccessOutcome) -> str:
        """
        Describe a failed read in plain language safe to show readers.
        """
        return (
            f"An article from {outcome.outlet_id} could not be used "
            f"({outcome.status.value.replace('_', ' ')})."
        )
