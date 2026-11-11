"""Test the in-process persistence boundary through observable save/load behavior.

The prototype intentionally loses state on restart. Request tests ensure retries
reuse completed work and cannot corrupt the authoritative conversation history."""

import pytest

from uuid import UUID
from concurrent.futures import ThreadPoolExecutor

from backend.sources.articles import ArticleRecord
from backend.agents.research_brief import ResearchBrief
from backend.agents.researcher_findings import ResearcherFindings
from backend.interfaces.http.chat_contracts import ChatRequest, ChatResponse
from backend.infrastructure.persistence import (
    InMemoryStore,
    RequestRecord,
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

    replacement: ChatRequest = request.model_copy(update={
        "conversation_id": record.conversation_id,
        "request_id": "replacement-turn",
    })
    assert store.begin_request(replacement)[1] is True


def test_failed_turn_leaves_the_conversation_available_for_a_new_request() -> None:
    """Replay the failure by request ID and accept new work with the same history."""
    store: InMemoryStore = InMemoryStore()
    request: ChatRequest = build_request()
    record: RequestRecord
    record, _ = store.begin_request(request)
    response: ChatResponse = ChatResponse(
        conversation_id=record.conversation_id,
        request_id=request.request_id,
        answer="Research failed.",
        tool_calls=[],
    )
    store.complete_request(response, status_code=502)

    replacement: ChatRequest = request.model_copy(update={
        "conversation_id": record.conversation_id,
        "request_id": "replacement-turn",
    })
    assert store.begin_request(replacement)[1] is True
    replay: RequestRecord
    should_start: bool
    replay, should_start = store.begin_request(request)
    assert should_start is False
    assert replay.response == response
    assert replay.response_status == 502
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


def test_oldest_idle_conversation_is_evicted_once_the_cap_is_exceeded() -> None:
    """Bound memory by dropping the least recently used finished conversation."""
    store: InMemoryStore = InMemoryStore(max_conversations=2)
    first: str = start_conversation(store, "first")
    second: str = start_conversation(store, "second")
    third: str = start_conversation(store, "third")

    with pytest.raises(KeyError):
        store.load_conversation(first)
    assert store.request_status("first") is None
    assert store.load_conversation(second) and store.load_conversation(third)


def test_a_running_conversation_is_never_evicted() -> None:
    """Do not drop a conversation while its turn is still being worked on."""
    store: InMemoryStore = InMemoryStore(max_conversations=2)
    running: str = start_conversation(store, "running", complete=False)
    idle: str = start_conversation(store, "idle")
    start_conversation(store, "newest")

    with pytest.raises(KeyError):
        store.load_conversation(idle)
    assert store.load_conversation(running) == ()


def test_continuing_a_conversation_protects_it_from_eviction() -> None:
    """Treat a follow-up as use, so the other idle conversation goes first."""
    store: InMemoryStore = InMemoryStore(max_conversations=2)
    older: str = start_conversation(store, "older")
    newer: str = start_conversation(store, "newer")
    follow_up: ChatRequest = ChatRequest.model_validate({
        "conversation_id": older, "request_id": "follow-up",
        "messages": [*[m.model_dump() for m in store.load_conversation(older)],
                     {"role": "user", "content": "More."}],
    })
    store.begin_request(follow_up)
    store.complete_request(ChatResponse(
        conversation_id=older, request_id="follow-up", answer="Done.", tool_calls=[],
    ))
    start_conversation(store, "third")

    with pytest.raises(KeyError):
        store.load_conversation(newer)
    assert store.load_conversation(older)
