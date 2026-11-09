"""
Behavior tests for the shared per-request budget.

The budget is the single place where search calls, article reads, model calls,
and the request deadline are counted for one request.
"""

from backend.application.settings import Settings
from backend.application.request_budget import BudgetResource, RequestBudget


class FakeClock:
    """
    Manually advanced clock so deadline behavior is deterministic.
    """

    def __init__(self) -> None:
        """
        Start the clock at zero seconds.
        """
        self.now: float = 0.0

    def __call__(self) -> float:
        """
        Return the current fake time in seconds.
        """
        return self.now


def test_resource_can_be_consumed_up_to_its_ceiling_then_refuses() -> None:
    """
    Each consumption succeeds until the configured ceiling is reached.
    """
    budget = RequestBudget(Settings(max_article_reads=2), clock=FakeClock())

    assert budget.try_consume(BudgetResource.ARTICLE_READS) is True
    assert budget.try_consume(BudgetResource.ARTICLE_READS) is True
    assert budget.try_consume(BudgetResource.ARTICLE_READS) is False


def test_resources_are_counted_independently() -> None:
    """
    Exhausting article reads does not block searches.
    """
    budget = RequestBudget(
        Settings(max_article_reads=1, max_search_calls=5),
        clock=FakeClock(),
    )
    budget.try_consume(BudgetResource.ARTICLE_READS)

    assert budget.try_consume(BudgetResource.ARTICLE_READS) is False
    assert budget.try_consume(BudgetResource.SEARCH_CALLS) is True


def test_passing_the_deadline_refuses_every_resource() -> None:
    """
    Once the request deadline passes nothing more may be consumed.
    """
    clock = FakeClock()
    budget = RequestBudget(Settings(request_deadline_seconds=10), clock=clock)
    clock.now = 11.0

    assert budget.deadline_exceeded() is True
    assert budget.try_consume(BudgetResource.SEARCH_CALLS) is False
    assert budget.try_consume(BudgetResource.MODEL_CALLS) is False
