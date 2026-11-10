"""
Lookups between political source groups and the project-controlled outlets.

Outlet assignments come only from the fixed roster, never from model output.
"""

from backend.sources.outlets import OUTLETS
from backend.agents.researcher_findings import SourceGroup


def outlets_for_group(group: SourceGroup) -> tuple[str, ...]:
    """
    Return the outlet IDs the roster assigns to a group.
    """
    return tuple(outlet.outlet_id for outlet in OUTLETS if outlet.group is group)


def group_for_outlet(outlet_id: str) -> SourceGroup | None:
    """
    Return the group an outlet belongs to, or None for an unknown outlet.
    """
    for outlet in OUTLETS:
        if outlet.outlet_id == outlet_id:
            return outlet.group
    return None


def outlet_display_name(outlet_id: str) -> str:
    """
    Return a reader-friendly outlet name, falling back to the outlet ID.
    """
    for outlet in OUTLETS:
        if outlet.outlet_id == outlet_id:
            return outlet.display_name
    return outlet_id
