"""Test the in-process persistence boundary through observable save/load behavior.

The prototype intentionally loses state on restart. Request tests ensure retries
reuse completed work and cannot corrupt the authoritative conversation history."""

import pytest

from uuid import UUID
from concurrent.futures import ThreadPoolExecutor

from backend.sources.articles import ArticleRecord
from backend.agents.research_brief import ResearchBrief
from backend.agents.researcher_findings import ResearcherFindings
from backend.infrastructure.persistence import InMemoryStore, RequestConflict
from backend.interfaces.http.chat_contracts import ChatRequest, ChatResponse


def build_request() -> ChatRequest:
    """Create one first-turn request whose retry has no conversation ID yet."""
    return ChatRequest.model_validate(
        {
            "conversation_id": None,
            "request_id": "first-turn",
            "messages": [{"role": "user", "content": "Compare coverage."}],
        },
    )


def test_first_turn_retry_reuses_the_completed_response_and_conversation() -> None:
    """Return the same saved result when the initial network response is lost."""
    store: InMemoryStore = InMemoryStore()
    request: ChatRequest = build_request()
    record, should_start = store.begin_request(request)
    assert should_start is True
    response: ChatResponse = ChatResponse(
        conversation_id=record.conversation_id,
        request_id=request.request_id,
        answer="Collected evidence.",
        tool_calls=[],
    )
    store.complete_request(response)

    repeated, should_restart = store.begin_request(request)

    assert should_restart is False
    assert repeated.conversation_id == response.conversation_id
    assert repeated.response == response


def test_request_id_cannot_be_reused_with_changed_payload() -> None:
    """Reject a changed question instead of replaying an unrelated response."""
    store: InMemoryStore = InMemoryStore()
    request: ChatRequest = build_request()
    store.begin_request(request)
    changed: ChatRequest = request.model_copy(deep=True)
    changed.messages[0].content = "A different event."

    with pytest.raises(RequestConflict):
        store.begin_request(changed)


def test_conversation_rejects_overlapping_turns() -> None:
    """Require one active turn in each conversation."""
    store: InMemoryStore = InMemoryStore()
    record, _ = store.begin_request(build_request())
    next_request: ChatRequest = ChatRequest.model_validate(
        {
            "conversation_id": record.conversation_id,
            "request_id": "next-turn",
            "messages": [{"role": "user", "content": "Another question."}],
        },
    )

    with pytest.raises(RequestConflict):
        store.begin_request(next_request)


def test_follow_up_must_include_exactly_the_saved_history() -> None:
    """Accept a real follow-up while rejecting client-invented assistant answers."""
    store: InMemoryStore = InMemoryStore()
    record, _ = store.begin_request(build_request())
    response: ChatResponse = ChatResponse(
        conversation_id=record.conversation_id,
        request_id=record.request.request_id,
        answer="Collected evidence.", tool_calls=[],
    )
    store.complete_request(response)
    history = store.load_conversation(record.conversation_id)
    next_request: ChatRequest = ChatRequest.model_validate(
        {
            "conversation_id": record.conversation_id,
            "request_id": "next-turn",
            "messages": [
                *[message.model_dump() for message in history],
                {"role": "user", "content": "Explain that further."},
            ],
        },
    )
    tampered: ChatRequest = next_request.model_copy(deep=True)
    tampered.messages[1].content = "An invented answer."

    with pytest.raises(RequestConflict):
        store.begin_request(tampered)
    _, should_start = store.begin_request(next_request)
    assert should_start is True


def test_interrupted_request_is_reported_without_automatic_restart() -> None:
    """Retain interruption status without adding unsaved messages to history."""
    store: InMemoryStore = InMemoryStore()
    request: ChatRequest = build_request()
    record, _ = store.begin_request(request)
    store.interrupt_request(request.request_id)

    repeated, should_restart = store.begin_request(request)

    assert should_restart is False
    assert repeated.status.value == "interrupted"
    assert store.load_conversation(record.conversation_id) == ()


def test_completed_request_cannot_be_completed_or_interrupted_again() -> None:
    """Protect completed history from duplicate writes and late cancellation."""
    store: InMemoryStore = InMemoryStore()
    record, _ = store.begin_request(build_request())
    response: ChatResponse = ChatResponse(
        conversation_id=record.conversation_id,
        request_id=record.request.request_id,
        answer="Collected evidence.", tool_calls=[],
    )
    store.complete_request(response)

    with pytest.raises(RequestConflict):
        store.complete_request(response)
    with pytest.raises(RequestConflict):
        store.interrupt_request(response.request_id)
    assert len(store.load_conversation(record.conversation_id)) == 2


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


def test_simultaneous_retries_only_claim_work_once() -> None:
    """Allow exactly one owner when the same request arrives concurrently."""
    store: InMemoryStore = InMemoryStore()
    request: ChatRequest = build_request()
    with ThreadPoolExecutor(max_workers=4) as executor:
        claims = list(executor.map(store.begin_request, [request] * 4))

    assert sum(should_start for _, should_start in claims) == 1
    assert len({record.conversation_id for record, _ in claims}) == 1


def test_new_store_cannot_restore_a_conversation_after_backend_restart() -> None:
    """Make the agreed process-local lifetime explicit at the public boundary."""
    store: InMemoryStore = InMemoryStore()
    record, _ = store.begin_request(build_request())

    with pytest.raises(KeyError):
        InMemoryStore().load_conversation(record.conversation_id)
