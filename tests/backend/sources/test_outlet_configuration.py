"""Check the fixed outlet roster used to restrict discovery and article reads.

The roster records attributed classifications and approved hosts; it does not
assert that every configured outlet has reliable automated access."""

from urllib.parse import urlsplit

from backend.sources.outlets import OUTLETS
from backend.agents.researcher_findings import SourceGroup


def test_roster_has_distinct_outlets_per_group_with_classification_provenance() -> None:
    """Keep political assignments fixed and preserve their review provenance."""
    assert len({outlet.outlet_id for outlet in OUTLETS}) == 15
    assert sum(outlet.group is SourceGroup.LIBERAL for outlet in OUTLETS) == 8
    assert sum(outlet.group is SourceGroup.CONSERVATIVE for outlet in OUTLETS) == 7
    assert all(outlet.classification_url for outlet in OUTLETS)
    assert all(
        outlet.classification_reviewed_on.isoformat() in ("2026-11-08", "2026-11-18")
        for outlet in OUTLETS
    )


def test_every_feed_host_is_authorized_for_its_outlet() -> None:
    """Each configured feed URL must be fetchable under its outlet's host allowance."""
    for outlet in OUTLETS:
        assert len(set(outlet.feed_urls)) == len(outlet.feed_urls)
        for feed_url in outlet.feed_urls:
            assert urlsplit(feed_url).netloc in outlet.feed_hosts, (outlet.outlet_id, feed_url)
