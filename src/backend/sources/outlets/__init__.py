"""Expose the project-controlled outlet roster and its typed configuration.

Consumers use these records for assigned hosts and classification provenance;
configuration membership does not guarantee that an article can be retrieved."""

from backend.sources.outlets.roster import OUTLETS, OutletConfiguration

__all__: list[str] = ["OUTLETS", "OutletConfiguration"]
