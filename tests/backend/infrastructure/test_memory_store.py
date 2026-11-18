"""Test the in-process persistence boundary through observable save/load behavior.

The prototype intentionally loses state on restart. These checks protect saved
article isolation, defensive copies of findings, and active conversation retention."""

import pytest

from uuid import UUID

from backend.sources.articles import ArticleRecord
from backend.agents.research_brief import ResearchBrief
from backend.agents.researcher_findings import ResearcherFindings
from backend.interfaces.http.chat_contracts import ChatRequest, ChatResponse
from backend.infrastructure.persistence import (
    InMemoryStore,
    RequestConflict,
)


def build_request() -> ChatRequest:
    """Create one first-turn request whose retry has no conversation ID yet."""
    return ChatRequest.model_validate(
        {
            "conversation_id": None,
            "request_id": "first-turn",
            "messages": [{"role": "user", "content": "Compare coverage."}],
        },
    )


def test_article_round_trip_is_scoped_to_its_conversation() -> None:
    """Keep saved evidence available to its session without leaking to another."""
    store: InMemoryStore = InMemoryStore()
    first, _ = store.begin_request(build_request())
    second, _ = store.begin_request(
        build_request().model_copy(update={"request_id": "other-conversation"}),
    )
    article_id: UUID = UUID("6ea317ce-d5c4-43ea-9ae8-d6c597af8b04")
    article: ArticleRecord = ArticleRecord.model_validate(
        {
            "article_id": str(article_id),
            "outlet_id": "npr",
            "requested_url": "https://www.npr.org/example",
            "canonical_url": "https://www.npr.org/example",
            "title": "Delegations meet for talks",
            "retrieved_at": "2026-11-08T21:00:00Z",
            "passages": [
                {"passage_id": f"{article_id}:p0001", "text": "Delegations met."},
            ],
        },
    )

    saved: ArticleRecord = store.save_article(first.conversation_id, article)

    assert store.load_article(first.conversation_id, article_id) == saved
    with pytest.raises(KeyError):
        store.load_article(second.conversation_id, article_id)
    with pytest.raises(RequestConflict):
        store.save_article(
            first.conversation_id,
            article.model_copy(update={"title": "Changed snapshot"}),
        )


def test_research_state_round_trip_does_not_expose_mutable_saved_findings() -> None:
    """Keep the brief and findings available for later questions in one session."""
    store: InMemoryStore = InMemoryStore()
    record, _ = store.begin_request(build_request())
    brief: ResearchBrief = ResearchBrief.model_validate(
        {
            "status": "clear", "event": "A specified event",
            "start_date": "2026-11-07", "end_date": "2026-11-08",
        },
    )
    findings: ResearcherFindings = ResearcherFindings.model_validate(
        {
            "group": "liberal", "article_ids": [],
            "main_focuses": [], "limitations": ["No full text"],
        },
    )
    store.save_research(record.conversation_id, brief, (findings,))

    saved_brief, saved_findings = store.load_research(record.conversation_id)
    saved_findings[0].limitations.clear()

    assert saved_brief == brief
    assert store.load_research(record.conversation_id)[1][0].limitations == [
        "No full text",
    ]


def start_conversation(store: InMemoryStore, name: str, complete: bool = True) -> str:
    """Begin a first turn named ``name`` and, by default, finish it."""
    request: ChatRequest = ChatRequest.model_validate({
        "conversation_id": None, "request_id": name,
        "messages": [{"role": "user", "content": name}],
    })
    record, _ = store.begin_request(request)
    if complete:
        store.complete_request(ChatResponse(
            conversation_id=record.conversation_id, request_id=name,
            answer="Done.", tool_calls=[],
        ))
    return record.conversation_id


def test_a_running_conversation_is_never_evicted() -> None:
    """Do not drop a conversation while its turn is still being worked on."""
    store: InMemoryStore = InMemoryStore(max_conversations=2)
    running: str = start_conversation(store, "running", complete=False)
    idle: str = start_conversation(store, "idle")
    start_conversation(store, "newest")

    with pytest.raises(KeyError):
        store.load_conversation(idle)
    assert store.load_conversation(running) == ()
