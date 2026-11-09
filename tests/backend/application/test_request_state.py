"""
Behavior tests for per-group research round limits kept in request state.
"""

from backend.agents.researcher_findings import SourceGroup
from backend.application.settings import Settings


def test_each_group_gets_its_own_research_round_allowance(make_state) -> None:
    """
    A group may start rounds up to the ceiling; the other group is unaffected.
    """
    state = make_state(Settings(max_research_rounds=2))

    assert state.try_start_round(SourceGroup.LIBERAL) is True
    assert state.try_start_round(SourceGroup.LIBERAL) is True
    assert state.try_start_round(SourceGroup.LIBERAL) is False
    assert state.try_start_round(SourceGroup.CONSERVATIVE) is True
