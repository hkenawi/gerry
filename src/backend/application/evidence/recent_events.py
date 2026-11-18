"""
Group dated headlines and order them for the front page or a chat search.

Python decides which stories count as events, using only dated headlines and
the number of distinct outlets, so the Lead can choose among real candidates
without inventing any. Headlines about one event share several distinctive words.
"""

import re

from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from backend.sources.access import ArticleCandidate

MAX_EVENT_CANDIDATES: int = 12
MINIMUM_OUTLETS: int = 2
RECENT_TIME_PHRASE: str = r"(?:right now|now|today|this week|lately)"
TOPIC_QUESTION: str = "How did different outlets cover “{topic}”?"
TOPIC_SELECTION: re.Pattern[str] = re.compile(
    re.escape(TOPIC_QUESTION).replace(re.escape("{topic}"), r".+"),
)
EVENT_TOPIC_PREFIX: re.Pattern[str] = re.compile(
    r"^(?:(?:any|current|latest|recent|the)\s+)*(?:events|headlines|news|updates)"
    r"\s+(?:about|around|from|in|on)\s+",
    re.IGNORECASE,
)
EVENT_TOPIC_SUFFIX: re.Pattern[str] = re.compile(
    rf"\s+{RECENT_TIME_PHRASE}$",
    re.IGNORECASE,
)
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
    snippet: str | None = None
    candidates: tuple[ArticleCandidate, ...] = ()


def normalize_event_topic(topic: str | None) -> str:
    """Remove generic headline phrasing while retaining the named subject."""
    query: str = " ".join((topic or "").split()).rstrip("?!. ")
    query = EVENT_TOPIC_PREFIX.sub("", query)
    return EVENT_TOPIC_SUFFIX.sub("", query)


def is_topic_selection(question: str) -> bool:
    """Recognize the undated question generated for a story selection."""
    return TOPIC_SELECTION.fullmatch(" ".join(question.split())) is not None


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


def publication_order(candidate: ArticleCandidate) -> datetime:
    """Sort timed headlines by publication time and date-only headlines by day."""
    published: date | datetime | None = candidate.published_at
    if isinstance(published, datetime):
        return published
    return datetime.combine(published or date.min, time.min, tzinfo=UTC)


def cluster_events(
    candidates: list[ArticleCandidate],
    limit: int = MAX_EVENT_CANDIDATES,
    *,
    require_shared_coverage: bool = True,
) -> tuple[EventCandidate, ...]:
    """
    Group related headlines. Chat searches use recency and the front page uses coverage.
    """
    groups: list[tuple[frozenset[str], list[tuple[ArticleCandidate, date]]]] = []
    if not require_shared_coverage:
        candidates = sorted(candidates, key=publication_order, reverse=True)
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
    clusters: list[list[tuple[ArticleCandidate, date]]] = [members for _, members in groups]
    if require_shared_coverage:
        clusters = [
            members for members in clusters
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
            snippet=members[0][0].snippet,
            candidates=tuple(member for member, _ in members),
        )
        for number, members in enumerate(clusters[:limit], start=1)
    )
