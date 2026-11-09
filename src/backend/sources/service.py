"""Expose source search, full article collection, and saved-evidence reads.

One small service binds the approved roster, network boundary, limits, and memory
store. Calls are synchronous; async agent wrappers should use asyncio.to_thread
so the two researchers can execute without blocking their event loop."""

import re
import logging

from uuid import UUID
from typing import TypeAlias
from lxml.etree import LxmlError
from datetime import date, datetime
from collections.abc import Callable

from backend.sources.articles import ArticleRecord
from backend.infrastructure.persistence import InMemoryStore
from backend.sources.articles.extraction import extract_article
from backend.sources.outlets import OUTLETS, OutletConfiguration
from backend.sources.constants import SOURCE_CONSTANTS, SourceAccessStatus
from backend.sources.discovery import build_discovery_urls, parse_discovery_document
from backend.sources.access import (
    ArticleCandidate,
    ArticleReadResult,
    ArticleSearchResult,
    SourceAccessOutcome,
)
from backend.sources.access.http import (
    SourceLimits,
    FetchedDocument,
    SourceAccessError,
    fetch_document,
    validate_source_url,
)


SourceFetcher: TypeAlias = Callable[[str, tuple[str, ...], SourceLimits], FetchedDocument]
logger: logging.Logger = logging.getLogger(__name__)


class ArticleSourceService:
    """Own restricted discovery and collection for the prototype's source tools."""

    def __init__(
        self,
        store: InMemoryStore,
        fetcher: SourceFetcher = fetch_document,
        limits: SourceLimits = SourceLimits(),
        outlets: tuple[OutletConfiguration, ...] = OUTLETS,
    ) -> None:
        """Receive concrete dependencies without creating model or global clients."""
        self._store: InMemoryStore = store
        self._fetch: SourceFetcher = fetcher
        self._limits: SourceLimits = limits
        self._outlets: dict[str, OutletConfiguration] = {
            outlet.outlet_id: outlet for outlet in outlets
        }

    def search_articles(
        self,
        query: str,
        start_date: date,
        end_date: date,
        assigned_outlets: tuple[str, ...],
    ) -> ArticleSearchResult:
        """Discover hints only within trusted outlet assignments and date bounds."""
        if start_date > end_date or not query.strip() or not assigned_outlets:
            raise ValueError("Search requires a query, outlet assignment, and valid dates.")
        candidates: list[ArticleCandidate] = []
        outcomes: list[SourceAccessOutcome] = []
        for outlet_id in dict.fromkeys(assigned_outlets):
            outlet: OutletConfiguration | None = self._outlets.get(outlet_id)
            if outlet is None:
                outcomes.append(SourceAccessOutcome(
                    outlet_id=outlet_id,
                    status=SOURCE_CONSTANTS.access_statuses.ACCESS_DENIED,
                    detail="Outlet is not in the approved roster.",
                ))
                continue
            urls, scope = build_discovery_urls(outlet, start_date, end_date, self._limits)
            found: list[ArticleCandidate] = []
            failures: list[SourceAccessError] = []
            for url in urls:
                try:
                    document: FetchedDocument = self._fetch(
                        url, tuple(dict.fromkeys((*outlet.feed_hosts, *outlet.article_hosts))),
                        self._limits,
                    )
                    self._validate_document(document, (*outlet.feed_hosts, *outlet.article_hosts))
                    found.extend(parse_discovery_document(
                        document, outlet, query, start_date, end_date,
                        expect_feed=url in outlet.feed_urls,
                    ))
                except SourceAccessError as error:
                    failures.append(error)
                except (OSError, ValueError, LxmlError):
                    failures.append(SourceAccessError(
                        SOURCE_CONSTANTS.access_statuses.FETCH_FAILED,
                        "Discovery document could not be fetched or parsed.",
                    ))
            unique: dict[str, ArticleCandidate] = {candidate.url: candidate for candidate in found}
            selected: list[ArticleCandidate] = list(unique.values())[:self._limits.max_results_per_outlet]
            candidates.extend(selected)
            last_error: SourceAccessError | None = failures[-1] if failures else None
            status: SourceAccessStatus = (
                SOURCE_CONSTANTS.access_statuses.SUCCESS if selected else
                last_error.status if last_error else SOURCE_CONSTANTS.access_statuses.NO_RESULTS
            )
            outcomes.append(SourceAccessOutcome(
                outlet_id=outlet_id, status=status,
                http_status=last_error.http_status if last_error and not selected else None,
                detail=scope + (" Some discovery pages failed." if failures else ""),
            ))
        return ArticleSearchResult(candidates=tuple(candidates), outcomes=tuple(outcomes))

    def read_article(
        self,
        url: str,
        outlet_id: str,
        conversation_id: str,
        start_date: date,
        end_date: date,
        assigned_outlets: tuple[str, ...],
    ) -> ArticleReadResult:
        """Fetch, extract, date-check, deduplicate, and save one assigned article."""
        if start_date > end_date:
            raise ValueError("Article dates must form a valid window.")
        try:
            outlet: OutletConfiguration | None = self._outlets.get(outlet_id)
            if outlet is None or outlet_id not in assigned_outlets:
                raise SourceAccessError(
                    SOURCE_CONSTANTS.access_statuses.ACCESS_DENIED,
                    "Outlet is outside the researcher's approved assignment.",
                )
            validated_url: str = validate_source_url(url, outlet.article_hosts)
            try:
                collected: tuple[ArticleRecord, ...] = self._store.list_articles(conversation_id)
            except Exception as error:
                raise SourceAccessError(
                    SOURCE_CONSTANTS.access_statuses.STORAGE_FAILED,
                    "Conversation evidence could not be loaded.",
                ) from error
            for saved in collected:
                if saved.outlet_id == outlet_id and validated_url in (
                    saved.requested_url, saved.canonical_url,
                ):
                    self._validate_article_date(saved, start_date, end_date)
                    return self._successful_read(saved, url)
            document: FetchedDocument = self._fetch(validated_url, outlet.article_hosts, self._limits)
            self._validate_document(document, outlet.article_hosts)
            if document.content_type.split(";", 1)[0].lower() not in (
                "text/html", "application/xhtml+xml",
            ):
                raise SourceAccessError(
                    SOURCE_CONSTANTS.access_statuses.EXTRACTION_FAILED,
                    "Source response is not an HTML article.",
                )
            article: ArticleRecord = extract_article(
                document, outlet_id, outlet.article_hosts, self._limits,
            ).model_copy(update={"requested_url": validated_url})
            self._validate_article_date(article, start_date, end_date)
            for saved in collected:
                if self._shares_reporting(article, saved):
                    if (
                        saved.outlet_id == outlet_id
                        and saved.canonical_url == article.canonical_url
                        and tuple(p.text for p in saved.passages)
                        == tuple(p.text for p in article.passages)
                    ):
                        return self._successful_read(saved, url)
                    article = article.model_copy(update={
                        "duplicate_of": saved.duplicate_of or saved.article_id,
                    })
                    break
            try:
                article = self._store.save_article(conversation_id, article)
            except Exception as error:
                logger.exception("Article storage failed.")
                raise SourceAccessError(
                    SOURCE_CONSTANTS.access_statuses.STORAGE_FAILED,
                    "Article could not be saved; it is not available as collected evidence.",
                ) from error
            return self._successful_read(article, url)
        except SourceAccessError as error:
            return ArticleReadResult(outcome=SourceAccessOutcome(
                outlet_id=outlet_id, url=url, status=error.status,
                http_status=error.http_status, detail=str(error),
            ))
        except OSError:
            return ArticleReadResult(outcome=SourceAccessOutcome(
                outlet_id=outlet_id, url=url,
                status=SOURCE_CONSTANTS.access_statuses.FETCH_FAILED,
                detail="Source fetch failed.",
            ))
        except (ValueError, LxmlError):
            logger.exception("Article extraction failed.")
            return ArticleReadResult(outcome=SourceAccessOutcome(
                outlet_id=outlet_id, url=url,
                status=SOURCE_CONSTANTS.access_statuses.EXTRACTION_FAILED,
                detail="Article text or metadata could not be validated.",
            ))

    def read_collected_article(self, conversation_id: str, article_id: UUID) -> ArticleRecord:
        """Read saved session evidence only; a missing snapshot raises KeyError."""
        return self._store.load_article(conversation_id, article_id)

    def _validate_document(self, document: FetchedDocument, hosts: tuple[str, ...]) -> None:
        """Revalidate injected fetch results before trusting their size and final URL."""
        validate_source_url(document.url, hosts)
        if document.status != 200 or len(document.body) > self._limits.max_response_bytes:
            raise SourceAccessError(
                SOURCE_CONSTANTS.access_statuses.FETCH_FAILED,
                "Source response failed its status or size validation.",
            )

    def _validate_article_date(
        self, article: ArticleRecord, start_date: date, end_date: date,
    ) -> None:
        """Enforce publication bounds on both newly extracted and reused evidence."""
        published: date | datetime | None = article.published_at
        if published is None:
            raise SourceAccessError(
                SOURCE_CONSTANTS.access_statuses.MISSING_DATE,
                "Saved article has no publication date.",
            )
        day: date = published.date() if isinstance(published, datetime) else published
        if not start_date <= day <= end_date:
            raise SourceAccessError(
                SOURCE_CONSTANTS.access_statuses.OUTSIDE_WINDOW,
                "Article was published outside the requested event window.",
            )

    def _shares_reporting(self, first: ArticleRecord, second: ArticleRecord) -> bool:
        """Recognize substantially shared text without merging publication choices."""
        def build_shingles(article: ArticleRecord) -> set[tuple[str, ...]]:
            """Represent article text as five-word sequences for duplicate comparison."""
            words: list[str] = re.findall(
                r"\w+", " ".join(passage.text for passage in article.passages).lower(),
            )
            return {tuple(words[index:index + 5]) for index in range(len(words) - 4)}

        first_text: set[tuple[str, ...]] = build_shingles(first)
        second_text: set[tuple[str, ...]] = build_shingles(second)
        union: set[tuple[str, ...]] = first_text | second_text
        return bool(union) and len(first_text & second_text) / len(union) >= self._limits.duplicate_similarity

    def _successful_read(self, article: ArticleRecord, requested_url: str) -> ArticleReadResult:
        """Return success only for an existing or successfully saved snapshot."""
        return ArticleReadResult(
            outcome=SourceAccessOutcome(
                outlet_id=article.outlet_id, url=requested_url,
                status=SOURCE_CONSTANTS.access_statuses.SUCCESS,
            ),
            article=article,
        )
