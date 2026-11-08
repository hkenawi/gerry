"""Exercise discovery and saved article reads through their public source boundary.

Fixtures replace only the external network. Real extraction, source validation,
date checks, duplicate handling, and conversation storage run together offline."""

import pytest

from datetime import date
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor

from backend.sources.service import ArticleSourceService
from backend.infrastructure.persistence import InMemoryStore
from backend.interfaces.http.chat_contracts import ChatRequest
from backend.sources.access.http import FetchedDocument, SourceLimits


ARTICLE_URL: str = "https://www.npr.org/story"
ARTICLE_HTML: bytes = b'''<html><head><title>Earthquake rescue efforts</title>
<link rel="canonical" href="https://www.npr.org/story">
<script type="application/ld+json">{"@type":"NewsArticle",
"url":"https://www.npr.org/story","headline":"Earthquake rescue efforts",
"datePublished":"2026-11-07T09:00:00-05:00",
"author":{"@type":"Person","name":"Example Reporter"}}</script>
</head><body><article><h1>Earthquake rescue efforts</h1>
<p>Emergency workers continued rescue operations after an earthquake damaged
several towns on Saturday. Local authorities said crews were searching buildings
and checking roads before allowing residents to return. Officials asked people
to follow evacuation notices while engineers inspected public infrastructure.</p>
<p>At a public briefing, the mayor described how temporary shelters were providing
food and clean water to displaced families. Volunteers helped register residents
and locate missing relatives. The city said additional supplies would arrive
after inspectors confirmed that the main bridge was safe for delivery trucks.</p>
<p>Hospital staff said emergency departments remained open and were coordinating
with ambulance crews. Schools would stay closed until structural inspections
were complete. Authorities planned another briefing on Sunday and said updated
information would be published as rescue teams reached the surrounding villages.</p>
</article></body></html>'''


def build_store() -> tuple[InMemoryStore, str]:
    """Create a real conversation so collection exercises authorized storage."""
    store: InMemoryStore = InMemoryStore()
    request: ChatRequest = ChatRequest.model_validate(
        {
            "conversation_id": None, "request_id": "source-test",
            "messages": [{"role": "user", "content": "Compare earthquake coverage."}],
        },
    )
    record, _ = store.begin_request(request)
    return store, record.conversation_id


def fetch_article(
    url: str, allowed_hosts: tuple[str, ...], limits: SourceLimits,
) -> FetchedDocument:
    """Return a known publisher page without contacting the network."""
    return FetchedDocument(url, ARTICLE_HTML, "text/html")


def test_article_read_saves_passages_and_reuses_collected_evidence() -> None:
    """Read full text once and recover the same snapshot using saved evidence only."""
    store, conversation_id = build_store()
    service: ArticleSourceService = ArticleSourceService(store, fetcher=fetch_article)

    result = service.read_article(
        ARTICLE_URL, "npr", conversation_id,
        date(2026, 11, 7), date(2026, 11, 8), ("npr",),
    )

    assert result.outcome.status.value == "success"
    assert result.article is not None
    assert result.article.bylines == ("Example Reporter",)
    assert result.article.passages[0].passage_id.endswith(":p0001")
    assert service.read_collected_article(
        conversation_id, result.article.article_id,
    ) == result.article


@pytest.mark.parametrize(
    "url, outlet_id, assigned, expected",
    [
        ("https://evil.example/story", "npr", ("npr",), "access_denied"),
        (ARTICLE_URL, "npr", ("fox",), "access_denied"),
    ],
)
def test_article_read_enforces_host_and_researcher_assignment(
    url: str, outlet_id: str, assigned: tuple[str, ...], expected: str,
) -> None:
    """Reject unassigned sources before invoking the injected network boundary."""
    store, conversation_id = build_store()

    def reject_network(
        requested: str, allowed: tuple[str, ...], limits: SourceLimits,
    ) -> FetchedDocument:
        """Fail if a forbidden request reaches the network."""
        raise AssertionError("Forbidden source reached the network.")

    service: ArticleSourceService = ArticleSourceService(store, fetcher=reject_network)
    result = service.read_article(
        url, outlet_id, conversation_id,
        date(2026, 11, 7), date(2026, 11, 8), assigned,
    )
    assert result.outcome.status.value == expected
    assert result.article is None


@pytest.mark.parametrize(
    "body, expected",
    [
        (ARTICLE_HTML.replace(b"2026-11-07T09:00:00-05:00", b"2025-04-21"), "outside_window"),
        (ARTICLE_HTML.replace(b'"datePublished":"2026-11-07T09:00:00-05:00",', b""), "missing_date"),
        (b"<html><article><p>A headline and a short teaser.</p></article></html>", "incomplete_text"),
        (ARTICLE_HTML.replace(b'"@type":"NewsArticle",', b'"@type":"NewsArticle","isAccessibleForFree":false,'), "paywall"),
    ],
)
def test_unusable_articles_are_excluded_with_explicit_reasons(
    body: bytes, expected: str,
) -> None:
    """Keep out-of-window, undated, incomplete, and gated content out of evidence."""
    store, conversation_id = build_store()

    def fetch_fixture(
        url: str, hosts: tuple[str, ...], limits: SourceLimits,
    ) -> FetchedDocument:
        """Supply one controlled publisher response."""
        return FetchedDocument(url, body, "text/html")

    result = ArticleSourceService(store, fetcher=fetch_fixture).read_article(
        ARTICLE_URL, "npr", conversation_id,
        date(2026, 11, 7), date(2026, 11, 8), ("npr",),
    )
    assert result.outcome.status.value == expected
    assert store.list_articles(conversation_id) == ()


def test_search_filters_feed_candidates_without_collecting_them() -> None:
    """Return dated assigned-outlet discovery hints while leaving storage empty."""
    store, conversation_id = build_store()
    feed: bytes = b'''<rss><channel><item><title>Earthquake rescue efforts</title>
<link>https://www.npr.org/story</link><description>Rescue workers help residents.</description>
<pubDate>Sat, 07 Nov 2026 09:00:00 -0500</pubDate></item></channel></rss>'''

    def fetch_feed(
        url: str, hosts: tuple[str, ...], limits: SourceLimits,
    ) -> FetchedDocument:
        """Supply a dated RSS item from the assigned publisher."""
        return FetchedDocument(url, feed, "application/rss+xml")

    result = ArticleSourceService(store, fetcher=fetch_feed).search_articles(
        "earthquake rescue", date(2026, 11, 7), date(2026, 11, 8), ("npr",),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].url == ARTICLE_URL
    assert store.list_articles(conversation_id) == ()


def test_same_article_is_reused_without_another_fetch() -> None:
    """Avoid a second source request for already collected session evidence."""
    store, conversation_id = build_store()
    calls: list[str] = []

    def fetch_once(
        url: str, hosts: tuple[str, ...], limits: SourceLimits,
    ) -> FetchedDocument:
        """Record outbound reads at the network boundary."""
        calls.append(url)
        return fetch_article(url, hosts, limits)

    service: ArticleSourceService = ArticleSourceService(store, fetcher=fetch_once)
    first = service.read_article(
        ARTICLE_URL, "npr", conversation_id,
        date(2026, 11, 7), date(2026, 11, 8), ("npr",),
    )
    second = service.read_article(
        ARTICLE_URL, "npr", conversation_id,
        date(2026, 11, 7), date(2026, 11, 8), ("npr",),
    )
    assert first.article is not None
    assert second.article == first.article
    assert len(calls) == 1


def test_duplicate_reporting_keeps_distinct_outlet_records() -> None:
    """Link matching reporting while preserving the two publication choices."""
    store, conversation_id = build_store()

    def fetch_copy(
        url: str, hosts: tuple[str, ...], limits: SourceLimits,
    ) -> FetchedDocument:
        """Supply the same reporting under each publisher's own canonical URL."""
        body: bytes = ARTICLE_HTML.replace(ARTICLE_URL.encode(), url.encode())
        return FetchedDocument(url, body, "text/html")

    service: ArticleSourceService = ArticleSourceService(store, fetcher=fetch_copy)
    first = service.read_article(
        ARTICLE_URL, "npr", conversation_id,
        date(2026, 11, 7), date(2026, 11, 8), ("npr",),
    )
    second = service.read_article(
        "https://www.foxnews.com/world/story", "fox", conversation_id,
        date(2026, 11, 7), date(2026, 11, 8), ("fox",),
    )
    assert first.article is not None and second.article is not None
    assert second.article.duplicate_of == first.article.article_id
    assert second.article.outlet_id != first.article.outlet_id


def test_storage_failure_never_returns_a_successful_article_read() -> None:
    """Preserve an explicit failure if the persistence boundary rejects a save."""
    from unittest.mock import patch

    store, conversation_id = build_store()
    service: ArticleSourceService = ArticleSourceService(store, fetcher=fetch_article)
    with patch.object(store, "save_article", side_effect=OSError("Unavailable")):
        result = service.read_article(
            ARTICLE_URL, "npr", conversation_id,
            date(2026, 11, 7), date(2026, 11, 8), ("npr",),
        )
    assert result.outcome.status.value == "storage_failed"
    assert result.article is None


def test_simultaneous_outlet_reads_preserve_exact_duplicate_relationships() -> None:
    """Keep matching reporting linked even when both researchers collect at once."""
    store, conversation_id = build_store()
    barrier: Barrier = Barrier(2)

    def fetch_together(
        url: str, hosts: tuple[str, ...], limits: SourceLimits,
    ) -> FetchedDocument:
        """Synchronize network responses while keeping extraction and storage real."""
        barrier.wait(timeout=3)
        return FetchedDocument(
            url, ARTICLE_HTML.replace(ARTICLE_URL.encode(), url.encode()), "text/html",
        )

    service: ArticleSourceService = ArticleSourceService(store, fetcher=fetch_together)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            service.read_article, ARTICLE_URL, "npr", conversation_id,
            date(2026, 11, 7), date(2026, 11, 8), ("npr",),
        )
        second = executor.submit(
            service.read_article, "https://www.foxnews.com/world/story", "fox",
            conversation_id, date(2026, 11, 7), date(2026, 11, 8), ("fox",),
        )
        first_article = first.result().article
        second_article = second.result().article

    assert first_article is not None and second_article is not None
    assert (
        first_article.duplicate_of == second_article.article_id
        or second_article.duplicate_of == first_article.article_id
    )
