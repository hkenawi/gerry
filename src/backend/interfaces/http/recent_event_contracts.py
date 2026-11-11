"""Define the dated edition and attributed headlines returned to the front page.

The HTTP layer translates approved outlet IDs into display names before sending
these models. The browser uses each reporting window to draft a chat question."""

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


class RecentEdition(BaseModel):
    """A recent discovery window with up to five multi-outlet stories."""

    start_date: date
    end_date: date
    events: list[RecentStory]
