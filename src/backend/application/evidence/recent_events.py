"""
Group discovered headlines into events reported by several approved outlets.

Python decides which stories count as events, using only dated headlines and
the number of distinct outlets, so the Lead can choose among real candidates
without inventing any. Headlines about one event share several distinctive words.
"""

import re

from datetime import date, datetime
from dataclasses import dataclass

from backend.sources.access import ArticleCandidate

MAX_EVENT_CANDIDATES: int = 12
MINIMUM_OUTLETS: int = 2
STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "after", "over", "from", "into", "that", "this",
    "says", "said", "amid", "about", "what", "will", "have", "has", "its", "are",
})


@dataclass(frozen=True)
class EventCandidate:
    """
    One event: a representative headline, its outlets, and when it was reported.
    """

    event_id: int
    headline: str
    headline_outlet: str
    outlet_ids: tuple[str, ...]
    first_date: date
    last_date: date


def headline_terms(title: str) -> frozenset[str]:
    """
    Return the distinctive lowercase words of a headline.
    """
    return frozenset(re.findall(r"[a-z0-9]{3,}", title.lower())) - STOPWORDS


def same_event(first: frozenset[str], second: frozenset[str]) -> bool:
    """
    Treat headlines as one event when they share at least two words, and half of the shorter.
    """
    shared: int = len(first & second)
    return shared >= 2 and shared / min(len(first), len(second)) >= 0.5


def cluster_events(
    candidates: list[ArticleCandidate],
    limit: int = MAX_EVENT_CANDIDATES,
) -> tuple[EventCandidate, ...]:
    """
    Return dated events reported by at least two distinct outlets, best supported first.
    """
    groups: list[tuple[frozenset[str], list[tuple[ArticleCandidate, date]]]] = []
    for candidate in candidates:
        published = candidate.published_at
        if published is None:
            continue
        day: date = published.date() if isinstance(published, datetime) else published
        terms: frozenset[str] = headline_terms(candidate.title)
        for group_terms, members in groups:
            if same_event(terms, group_terms):
                members.append((candidate, day))
                break
        else:
            groups.append((terms, [(candidate, day)]))
    clusters = [
        members for _, members in groups
        if len({member.outlet_id for member, _ in members}) >= MINIMUM_OUTLETS
    ]
    clusters.sort(key=lambda members: (
        -len({member.outlet_id for member, _ in members}),
        -max(day for _, day in members).toordinal(),
    ))
    return tuple(
        EventCandidate(
            event_id=number,
            headline=members[0][0].title,
            headline_outlet=members[0][0].outlet_id,
            outlet_ids=tuple(dict.fromkeys(member.outlet_id for member, _ in members)),
            first_date=min(day for _, day in members),
            last_date=max(day for _, day in members),
        )
        for number, members in enumerate(clusters[:limit], start=1)
    )
