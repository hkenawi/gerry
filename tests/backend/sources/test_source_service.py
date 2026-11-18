"""Exercise discovery and saved article reads through their public source boundary.

Fixtures replace only the external network. Real extraction, source validation,
date checks, duplicate handling, and conversation storage run together offline."""

import pytest

from datetime import date
from xml.sax.saxutils import escape

from backend.application.settings import Settings
from backend.sources.articles import ArticleRecord
from backend.agents.researcher_findings import SourceGroup
from backend.application.evidence.outlet_assignments import outlets_for_group
from backend.sources.service import ArticleSourceService
from backend.infrastructure.persistence import InMemoryStore
from backend.application.turn.run_turn import TurnResult, run_turn
from backend.sources.access.http import FetchedDocument, SourceLimits
from backend.sources.access import ArticleReadResult, ArticleSearchResult
from backend.interfaces.http.chat_contracts import ChatMessage, ChatRequest
from support.scripted_model import FinalOutput, ModelCall, ScriptedModel, ToolCalls
from backend.application.turn.request_state import RequestState, build_request_state


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


async def test_turn_uses_real_source_discovery_extraction_and_evidence_storage() -> None:
    """Run one cited comparison with the model and outbound HTTP scripted."""
    store, conversation_id = build_store()
    urls: tuple[str, ...] = (
        ARTICLE_URL,
        "https://abcnews.com/earthquake-rescue",
        "https://www.foxnews.com/world/earthquake-rescue",
        "https://dailycaller.com/earthquake-rescue",
    )
    entries: str = "".join(
        f"<item><title>Earthquake rescue efforts</title><link>{escape(url)}</link>"
        "<pubDate>Sat, 07 Nov 2026 09:00:00 -0500</pubDate></item>"
        for url in urls
    )
    feed: bytes = f"<rss><channel>{entries}</channel></rss>".encode()

    def fetch_fixture(
        url: str,
        hosts: tuple[str, ...],
        limits: SourceLimits,
    ) -> FetchedDocument:
        """Return archive or feed items and serve their corresponding article bodies."""
        if url in urls:
            return FetchedDocument(
                url, ARTICLE_HTML.replace(ARTICLE_URL.encode(), url.encode()), "text/html",
            )
        return FetchedDocument(url, feed, "application/rss+xml")

    state: RequestState = build_request_state(
        conversation_id, Settings(), store,
        ArticleSourceService(store, fetcher=fetch_fixture),
    )
    brief: dict[str, str] = {
        "event": "Earthquake rescue", "start_date": "0001-01-01", "end_date": "2026-11-08",
    }

    def reply(call: ModelCall) -> ToolCalls | FinalOutput:
        """Drive each real agent using the citations returned by the source tools."""
        outputs: list[str] = call.tool_results
        if "You are the Lead" in call.system_instructions:
            if not outputs:
                return ToolCalls([
                    (f"research_{group}_coverage", {"event": brief["event"], "focus_question": None})
                    for group in ("liberal", "conservative")
                ])
            if len(outputs) == 2:
                saved: tuple[ArticleRecord, ...] = store.list_articles(conversation_id)

                def treatment(group: SourceGroup) -> dict[str, object]:
                    """Cite the first passage of an article saved for this group."""
                    article = next(a for a in saved if a.outlet_id in outlets_for_group(group))
                    return {
                        "state": "central_focus", "note": "Reported rescue work.",
                        "passage_ids": [article.passages[0].passage_id],
                    }

                alignment = [{
                    "aspect": "Rescue work",
                    "liberal": treatment(SourceGroup.LIBERAL),
                    "conservative": treatment(SourceGroup.CONSERVATIVE),
                }]
                return ToolCalls([("write_answer", {"question": brief["event"], "alignment": alignment})])
            return FinalOutput({"brief": {**brief, "status": "clear"}})
        if "You are the Writer" in call.system_instructions:
            saved: tuple[ArticleRecord, ...] = store.list_articles(conversation_id)
            passage_ids: list[str] = [article.passages[0].passage_id for article in saved]
            assert len(passage_ids) == 4
            assert all(passage_id in call.input_text for passage_id in passage_ids)
            claim: dict[str, str | list[str]] = {
                "text": "Both groups reported rescue work after the earthquake.",
                "passage_ids": passage_ids,
            }
            return FinalOutput({"summary": [claim], "overlap": [claim]})
        if not outputs:
            return ToolCalls([("search_articles", {"query": brief["event"]})])
        if len(outputs) == 1:
            search: ArticleSearchResult = ArticleSearchResult.model_validate_json(outputs[0])
            return ToolCalls([
                ("read_article", {"url": candidate.url, "outlet_id": candidate.outlet_id})
                for candidate in search.candidates
            ])
        reads: list[ArticleReadResult] = [
            ArticleReadResult.model_validate_json(output) for output in outputs[1:]
        ]
        return FinalOutput({
            "group": "liberal" if "Source group: liberal" in call.input_text else "conservative",
            "article_ids": [str(read.article.article_id) for read in reads if read.article],
            "main_focuses": [], "limitations": [],
        })

    result: TurnResult = await run_turn(
        [ChatMessage.model_validate({"role": "user", "content": "How did different outlets cover “Paris protests”?"})],
        state, ScriptedModel(reply), today=date(2026, 11, 8),
    )

    assert result.failure is None
    assert result.answer.startswith("Both groups reported rescue work after the earthquake. [1]")
    assert "### Rescue work" in result.answer
    assert "Reported rescue work." in result.answer
    assert "## Sources" in result.answer
    assert {article.canonical_url for article in state.store.list_articles(state.conversation_id)} == set(urls)


def build_store() -> tuple[InMemoryStore, str]:
    """Create a real conversation so collection exercises authorized storage."""
    store: InMemoryStore = InMemoryStore()
    request: ChatRequest = ChatRequest.model_validate(
        {
            "conversation_id": None, "request_id": "source-test",
            "messages": [{"role": "user", "content": "How did different outlets cover “Paris protests”?"}],
        },
    )
    record, _ = store.begin_request(request)
    return store, record.conversation_id


def fetch_article(
    url: str, allowed_hosts: tuple[str, ...], limits: SourceLimits,
) -> FetchedDocument:
    """Return a known publisher page without contacting the network."""
    return FetchedDocument(url, ARTICLE_HTML, "text/html")


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
        (b"<html><article><p>A headline and a short teaser.</p></article></html>", "incomplete_text"),
        (ARTICLE_HTML.replace(b'"@type":"NewsArticle",', b'"@type":"NewsArticle","isAccessibleForFree":false,'), "paywall"),
    ],
)
def test_unusable_articles_are_excluded_with_explicit_reasons(
    body: bytes, expected: str,
) -> None:
    """Keep incomplete and gated content out of saved evidence."""
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


def test_feed_replacement_page_is_reported_as_an_extraction_failure() -> None:
    """Distinguish unusable feed responses from searches that found no matches."""
    store, _ = build_store()

    def fetch_replacement(
        url: str,
        hosts: tuple[str, ...],
        limits: SourceLimits,
    ) -> FetchedDocument:
        """Return an HTML replacement page in place of the publisher's feed."""
        return FetchedDocument(url, b"<html><p>Feed unavailable</p></html>", "text/html")

    service: ArticleSourceService = ArticleSourceService(store, fetcher=fetch_replacement)
    result = service.search_articles(
        "earthquake", date(2026, 11, 7), date(2026, 11, 8), ("npr",),
    )

    assert result.outcomes[0].status.value == "extraction_failed"
    assert result.candidates == ()


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
    assert service.read_collected_article(
        conversation_id, first.article.article_id,
    ) == first.article
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


def test_unexpected_error_for_one_outlet_does_not_stop_the_search() -> None:
    """A crash while searching one outlet leaves the other outlet's candidates intact."""
    store, _ = build_store()
    feed: bytes = b'''<rss><channel><item><title>Earthquake rescue efforts</title>
<link>https://www.npr.org/story</link><description>Rescue workers help residents.</description>
<pubDate>Sat, 07 Nov 2026 09:00:00 -0500</pubDate></item></channel></rss>'''

    def fetch_mixed(url: str, hosts: tuple[str, ...], limits: SourceLimits) -> FetchedDocument:
        """Crash for one publisher and serve a feed for the other."""
        if "npr.org" not in url:
            raise RuntimeError("unexpected parser crash")
        return FetchedDocument(url, feed, "application/rss+xml")

    result = ArticleSourceService(store, fetcher=fetch_mixed).search_articles(
        "earthquake rescue", date(2026, 11, 7), date(2026, 11, 8), ("npr", "fox"),
    )

    statuses = {outcome.outlet_id: outcome.status.value for outcome in result.outcomes}
    assert statuses == {"npr": "success", "fox": "fetch_failed"}
    assert len(result.candidates) == 1


def test_unfiltered_feed_discovery_includes_older_entries_and_bypasses_search_cap() -> None:
    """The top-stories pool includes dated entries across the entire feed snapshot."""
    store, _ = build_store()
    feed: bytes = b'''<rss><channel>
<item><title>Quake rocks coastal city</title><link>https://www.nbcnews.com/a</link>
<pubDate>2026-11-07</pubDate></item>
<item><title>Election results announced</title><link>https://www.nbcnews.com/b</link>
<pubDate>2026-05-07</pubDate></item></channel></rss>'''

    def fetch_feed(url: str, hosts: tuple[str, ...], limits: SourceLimits) -> FetchedDocument:
        """Serve the same two-item feed for every request."""
        return FetchedDocument(url, feed, "application/rss+xml")

    service: ArticleSourceService = ArticleSourceService(
        store, fetcher=fetch_feed, limits=SourceLimits(max_results_per_outlet=1),
    )
    end: date = date(2026, 11, 8)
    everything: ArticleSearchResult = service.discover_headlines("", date.min, end, ("nbc",))
    filtered: ArticleSearchResult = service.discover_headlines("quake", date.min, end, ("nbc",))
    alternate: ArticleSearchResult = service.discover_headlines(
        "ballot count | election results", date.min, end, ("nbc",),
    )

    assert [c.title for c in everything.candidates] == [
        "Quake rocks coastal city", "Election results announced",
    ]
    assert [c.title for c in filtered.candidates] == ["Quake rocks coastal city"]
    assert [c.title for c in alternate.candidates] == ["Election results announced"]
