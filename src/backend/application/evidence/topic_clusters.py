"""
Turn model-proposed topics into validated options the reader can choose from.

The clusterer model only groups numbered headlines. Code checks that every number
is real, that each topic spans at least two outlets, and ranks the result, so no
topic can exist without headlines found in the sources.
"""

import re

from dataclasses import dataclass
from datetime import date, datetime

from backend.sources.access import ArticleCandidate
from backend.agents.topics.schemas import MAX_TOPICS, TopicProposal
from backend.application.evidence.recent_events import (
    MINIMUM_OUTLETS,
    cluster_events,
    headline_terms,
)

MAX_HEADLINES_FOR_CLUSTERING: int = 40
LABEL_UNSAFE: re.Pattern[str] = re.compile(r"[“”\"\[\]\\`<>]")


@dataclass(frozen=True)
class TopicOption:
    """
    One topic a reader can pick: a neutral label and the coverage behind it.
    """

    label: str
    outlet_ids: tuple[str, ...]
    first_date: date
    last_date: date
    headlines: tuple[str, ...]


def candidate_day(candidate: ArticleCandidate) -> date | None:
    """
    Return the publication day of a headline, or None when it is undated.
    """
    published: date | datetime | None = candidate.published_at
    if published is None:
        return None
    return published.date() if isinstance(published, datetime) else published


def select_headlines(
    candidates: list[ArticleCandidate],
    query_terms: frozenset[str] = frozenset(),
    limit: int = MAX_HEADLINES_FOR_CLUSTERING,
) -> list[ArticleCandidate]:
    """
    Keep distinct dated headlines, best term matches first and then newest first.
    """
    seen: set[str] = set()
    dated: list[tuple[ArticleCandidate, date]] = []
    for candidate in candidates:
        day: date | None = candidate_day(candidate)
        if day is None or candidate.url in seen:
            continue
        seen.add(candidate.url)
        dated.append((candidate, day))
    dated.sort(key=lambda item: (
        -len(query_terms & headline_terms(item[0].title)), -item[1].toordinal(),
    ))
    return [candidate for candidate, _ in dated[:limit]]


def describe_headlines(candidates: list[ArticleCandidate], outlet_name: dict[str, str]) -> str:
    """
    Number the headlines for the clusterer with their outlet and date.
    """
    return "\n".join(
        f"{number}. [{outlet_name.get(item.outlet_id, item.outlet_id)}, "
        f"{candidate_day(item)}] {' '.join(item.title.split())}"
        for number, item in enumerate(candidates, start=1)
    )


def find_proposal_problems(proposal: TopicProposal, headline_count: int) -> str | None:
    """
    Reject numbers that do not exist or headlines used by more than one topic.
    """
    used: set[int] = set()
    for topic in proposal.topics:
        for number in topic.headline_numbers:
            if not 1 <= number <= headline_count:
                return f"Headline number {number} does not exist; use 1 to {headline_count}."
            if number in used:
                return f"Headline number {number} appears in more than one topic."
            used.add(number)
    return None


def clean_label(label: str) -> str:
    """
    Collapse whitespace and drop characters that would break the choice link.
    """
    return " ".join(LABEL_UNSAFE.sub("", label).split())


def build_topic_options(
    proposal: TopicProposal,
    candidates: list[ArticleCandidate],
) -> tuple[TopicOption, ...]:
    """
    Keep topics backed by real headlines from at least two outlets, best covered first.
    """
    options: list[TopicOption] = []
    labels: set[str] = set()
    for topic in proposal.topics:
        label: str = clean_label(topic.label)
        members: list[ArticleCandidate] = [
            candidates[number - 1] for number in dict.fromkeys(topic.headline_numbers)
            if 1 <= number <= len(candidates)
        ]
        outlets: tuple[str, ...] = tuple(dict.fromkeys(member.outlet_id for member in members))
        days: list[date] = [day for member in members if (day := candidate_day(member))]
        if len(label) < 3 or label.casefold() in labels or len(outlets) < MINIMUM_OUTLETS or not days:
            continue
        labels.add(label.casefold())
        options.append(TopicOption(
            label, outlets, min(days), max(days), tuple(member.title for member in members),
        ))
    options.sort(key=lambda option: (-len(option.outlet_ids), -option.last_date.toordinal()))
    return tuple(options[:MAX_TOPICS])


def word_overlap_topics(candidates: list[ArticleCandidate]) -> tuple[TopicOption, ...]:
    """
    Last resort without a model: group headlines by shared words, labelled by one headline.
    """
    return tuple(
        TopicOption(
            clean_label(event.headline), event.outlet_ids, event.first_date, event.last_date,
            (event.headline,),
        )
        for event in cluster_events(candidates, MAX_TOPICS)
        if len(clean_label(event.headline)) >= 3
    )


def rank_related(
    options: tuple[TopicOption, ...],
    query_terms: frozenset[str],
    exclude: tuple[TopicOption, ...] = (),
) -> tuple[TopicOption, ...]:
    """
    Order topics by how many of the reader's words their headlines share.
    """
    taken: set[str] = {headline for option in exclude for headline in option.headlines}
    candidates: list[TopicOption] = [
        option for option in options if not taken & set(option.headlines)
    ]

    def overlap(option: TopicOption) -> int:
        """Count the reader's words found in the topic's headlines."""
        terms: frozenset[str] = frozenset().union(*(headline_terms(h) for h in option.headlines))
        return len(query_terms & terms)

    candidates.sort(key=lambda option: (
        -overlap(option), -len(option.outlet_ids), -option.last_date.toordinal(),
    ))
    return tuple(candidates)
