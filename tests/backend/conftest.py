"""
Shared fixtures for backend tests.

``make_article`` builds valid saved article records so tests describe only the
fields that matter to the behavior under test.
"""

from uuid import UUID, uuid4
from typing import Callable
from datetime import UTC, date, datetime

import pytest

from backend.sources.articles import ArticleRecord
from backend.sources.constants import ArticleType
from backend.application.settings import Settings
from backend.interfaces.http.chat_contracts import ChatRequest
from backend.infrastructure.persistence import InMemoryStore
from backend.sources.access import (
    ArticleReadResult,
    ArticleSearchResult,
    SourceAccessOutcome,
)
from backend.application.request_state import RequestState, build_request_state


@pytest.fixture
def make_article() -> Callable[..., ArticleRecord]:
    """
    Provide a factory for valid article records with sensible defaults.
    """

    def build_article(
        outlet_id: str = "npr",
        article_type: ArticleType = ArticleType.REPORTING,
        article_id: UUID | None = None,
        paragraphs: int = 3,
    ) -> ArticleRecord:
        """
        Build one valid article snapshot with sequential passage IDs.
        """
        identifier: UUID = article_id or uuid4()
        return ArticleRecord(
            article_id=identifier,
            outlet_id=outlet_id,
            requested_url=f"https://example.com/{identifier}",
            canonical_url=f"https://example.com/{identifier}",
            title=f"Title {identifier}",
            retrieved_at=datetime.now(UTC),
            article_type=article_type,
            passages=tuple(
                {
                    "passage_id": f"{identifier}:p{number:04d}",
                    "text": f"Paragraph {number} of {identifier}.",
                }
                for number in range(1, paragraphs + 1)
            ),
        )

    return build_article


class FakeSources:
    """
    Scriptable stand-in for the article source service.

    Reads pop results from ``read_script``, keyed by URL. A successful result's
    article is saved to the store so validation sees real saved evidence.
    """

    def __init__(self, store: InMemoryStore, conversation_id: str) -> None:
        """
        Start with empty scripts and call logs.
        """
        self.store: InMemoryStore = store
        self.conversation_id: str = conversation_id
        self.read_script: dict[str, list[ArticleReadResult]] = {}
        self.search_result: ArticleSearchResult | None = None
        self.search_calls: list[dict[str, object]] = []
        self.read_calls: list[dict[str, object]] = []

    def search_articles(
        self,
        query: str,
        start_date: date,
        end_date: date,
        assigned_outlets: tuple[str, ...],
    ) -> ArticleSearchResult:
        """
        Record the call and return the scripted search result.
        """
        self.search_calls.append(
            {
                "query": query,
                "start_date": start_date,
                "end_date": end_date,
                "assigned_outlets": assigned_outlets,
            }
        )
        if self.search_result is not None:
            return self.search_result
        return ArticleSearchResult(
            outcomes=tuple(
                SourceAccessOutcome(outlet_id=outlet, status="no_results")
                for outlet in assigned_outlets
            )
        )

    def read_article(
        self,
        url: str,
        outlet_id: str,
        conversation_id: str,
        start_date: date,
        end_date: date,
        assigned_outlets: tuple[str, ...],
    ) -> ArticleReadResult:
        """
        Record the call, save a successful article, and return the next result.
        """
        self.read_calls.append(
            {
                "url": url,
                "outlet_id": outlet_id,
                "assigned_outlets": assigned_outlets,
            }
        )
        result: ArticleReadResult = self.read_script[url].pop(0)
        if result.article is not None:
            self.store.save_article(conversation_id, result.article)
        return result

    def read_collected_article(
        self,
        conversation_id: str,
        article_id: UUID,
    ) -> ArticleRecord:
        """
        Return saved evidence only.
        """
        return self.store.load_article(conversation_id, article_id)


@pytest.fixture
def fake_sources() -> FakeSources:
    """
    Provide fake sources backed by a fresh store and conversation.
    """
    store = InMemoryStore()
    record, _ = store.begin_request(
        ChatRequest.model_validate(
            {
                "conversation_id": None,
                "request_id": "setup",
                "messages": [{"role": "user", "content": "setup"}],
            }
        )
    )
    conversation_id = record.conversation_id
    return FakeSources(store, conversation_id)


@pytest.fixture
def make_state(fake_sources: FakeSources) -> Callable[..., RequestState]:
    """
    Provide a factory for request state wired to the fake sources.
    """

    def build_state(settings: Settings | None = None) -> RequestState:
        """
        Build request state with a fresh budget and recorder.
        """
        return build_request_state(
            conversation_id=fake_sources.conversation_id,
            settings=settings or Settings(),
            store=fake_sources.store,
            sources=fake_sources,
        )

    return build_state
