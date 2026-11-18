"""Define the dated edition and attributed headlines returned to the front page.

The HTTP layer translates approved outlet IDs into display names before sending
these models. The browser uses the edition date to label the front page."""

from uuid import UUID
from datetime import date
from pydantic import BaseModel


class RecentStory(BaseModel):
    """One representative headline and its reporting dates and publishers."""

    headline: str
    headline_outlet: str
    reported_by: list[str]
    first_date: date
    last_date: date
    snippet: str | None
    issue_id: UUID | None = None


class RecentEdition(BaseModel):
    """A current-feed edition with up to five multi-outlet stories."""

    end_date: date
    events: list[RecentStory]
