"""
Shared per-request budget for searches, reads, model calls, and time.

One instance is created for each request and shared by every agent and tool so
that retries and parallel researchers cannot stack independent limits. All
consumption happens on the request's event loop, so no locking is required.
"""

import time
from enum import StrEnum
from typing import Callable

from backend.application.settings import Settings


class BudgetResource(StrEnum):
    """
    The countable resources a request may consume.
    """

    SEARCH_CALLS = "search_calls"
    ARTICLE_READS = "article_reads"
    MODEL_CALLS = "model_calls"


class RequestBudget:
    """
    Count consumption against the configured ceilings and the request deadline.
    """

    def __init__(
        self,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        Start the deadline clock and zero every counter.
        """
        self._clock: Callable[[], float] = clock
        self._started_at: float = clock()
        self._deadline_seconds: int = settings.request_deadline_seconds
        self._ceilings: dict[BudgetResource, int] = {
            BudgetResource.SEARCH_CALLS: settings.max_search_calls,
            BudgetResource.ARTICLE_READS: settings.max_article_reads,
            BudgetResource.MODEL_CALLS: settings.max_model_calls,
        }
        self._used: dict[BudgetResource, int] = {
            resource: 0 for resource in BudgetResource
        }

    def deadline_exceeded(self) -> bool:
        """
        Report whether the request has run past its deadline.
        """
        return self._clock() - self._started_at > self._deadline_seconds

    def try_consume(self, resource: BudgetResource) -> bool:
        """
        Consume one unit if the deadline and ceiling allow it, else refuse.
        """
        if self.deadline_exceeded():
            return False
        if self._used[resource] >= self._ceilings[resource]:
            return False
        self._used[resource] += 1
        return True
