"""Check the fixed outlet roster used to restrict discovery and article reads.

The roster records attributed classifications and approved hosts; it does not
assert that every configured outlet has reliable automated access."""

from backend.sources.outlets import OUTLETS
from backend.agents.researcher_findings import SourceGroup


def test_roster_has_five_distinct_outlets_per_group_with_classification_provenance() -> None:
    """Keep political assignments fixed and preserve their review provenance."""
    assert len({outlet.outlet_id for outlet in OUTLETS}) == 10
    assert sum(outlet.group is SourceGroup.LIBERAL for outlet in OUTLETS) == 5
    assert sum(outlet.group is SourceGroup.CONSERVATIVE for outlet in OUTLETS) == 5
    assert all(outlet.classification_url for outlet in OUTLETS)
    assert all(outlet.classification_reviewed_on.isoformat() == "2026-11-08" for outlet in OUTLETS)
