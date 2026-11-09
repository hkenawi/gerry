"""
Behavior tests for the HTTP application, called in-process with async httpx.

No real server, network, or model provider is involved.
"""

import asyncio

from collections.abc import Callable
from httpx import Response, AsyncClient, ASGITransport

from backend.sources.articles import ArticleRecord
from backend.agents.research_brief import ResearchBrief
from backend.application.settings import Settings
from backend.application.composition import build_app
from backend.infrastructure.persistence import InMemoryStore
from backend.agents.researcher_findings import ResearcherFindings
from backend.interfaces.http.chat_contracts import ChatRequest, ChatResponse
from support.scripted_model import FinalOutput, ModelCall, ScriptedModel, ToolCalls


def clarify(call: ModelCall) -> FinalOutput:
    """Script the Lead's clarification response without invoking a provider."""
    return FinalOutput({"brief": {
        "status": "needs_clarification",
        "event": "",
        "clarifying_question": "Which event and dates should I compare?",
    }})


def build_client(model: ScriptedModel | None = None) -> AsyncClient:
    """
    Build an async client that calls the application directly in-process.
    """
    return AsyncClient(
        transport=ASGITransport(app=build_app(Settings(), model or ScriptedModel(clarify))),
        base_url="http://test",
    )


async def test_health_endpoint_reports_ok() -> None:
    """
    The health endpoint lets Cloud Run and developers confirm the app started.
    """
    async with build_client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_chat_runs_the_workflow_and_replays_the_first_turn() -> None:
    """
    A valid turn gets a conversation ID, its own request ID, an answer, and calls.
    """
    model: ScriptedModel = ScriptedModel(clarify)
    payload: dict[str, object] = {
        "conversation_id": None,
        "request_id": "turn-1",
        "messages": [{"role": "user", "content": "Compare coverage."}],
    }
    async with build_client(model) as client:
        response = await client.post("/chat", json=payload)
        retry = await client.post("/chat", json=payload)
        conflict = await client.post("/chat", json={
            **payload, "messages": [{"role": "user", "content": "Different question"}],
        })
        progress = await client.get("/chat/progress/turn-1")

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"conversation_id", "request_id", "answer", "tool_calls"}
    assert body["request_id"] == "turn-1"
    assert body["conversation_id"] != ""
    assert body["tool_calls"] == []
    assert body["answer"] == "Which event and dates should I compare?"
    assert retry.json() == body
    assert conflict.status_code == 409
    assert len(model.calls) == 1
    assert "event: agent_started" in progress.text
    assert "event: agent_finished" in progress.text


async def test_chat_rejects_invalid_body_with_422() -> None:
    """
    A request that breaks the contract is refused before any work starts.
    """
    async with build_client() as client:
        response = await client.post(
            "/chat",
            json={"conversation_id": None, "request_id": "", "messages": []},
        )

    assert response.status_code == 422
    assert set(response.json()) == {"conversation_id", "request_id", "answer", "tool_calls"}


async def test_retry_during_a_running_turn_does_not_start_another_model_call() -> None:
    """Surface an in-flight request and allow its original response to finish."""
    started: asyncio.Event = asyncio.Event()
    finish: asyncio.Event = asyncio.Event()

    async def pause_model(call: ModelCall) -> FinalOutput:
        """Hold the Lead until the duplicate request has arrived."""
        started.set()
        await finish.wait()
        return clarify(call)

    model: ScriptedModel = ScriptedModel(pause_model)
    payload: dict[str, object] = {
        "conversation_id": None,
        "request_id": "running-turn",
        "messages": [{"role": "user", "content": "Compare coverage."}],
    }
    async with build_client(model) as client:
        first: asyncio.Task[Response] = asyncio.create_task(client.post("/chat", json=payload))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            retry: Response = await client.post("/chat", json=payload)
            assert retry.status_code == 409
            assert retry.headers["Retry-After"] == "1"
        finally:
            finish.set()
            response: Response = await asyncio.wait_for(first, timeout=2)
    assert response.status_code == 200
    assert len(model.calls) == 1


async def test_blank_model_answer_replays_as_a_failure_without_appending_history() -> None:
    """Keep invalid model output out of conversation history and cache the failure."""
    def blank_reply(call: ModelCall) -> FinalOutput:
        """Return a whitespace-only clarification from the model."""
        return FinalOutput({"brief": {
            "status": "needs_clarification", "event": "", "clarifying_question": "   ",
        }})

    model: ScriptedModel = ScriptedModel(blank_reply)
    app = build_app(Settings(), model)
    payload: dict[str, object] = {
        "conversation_id": None, "request_id": "blank-answer",
        "messages": [{"role": "user", "content": "Compare coverage."}],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first: Response = await client.post("/chat", json=payload)
        retry: Response = await client.post("/chat", json=payload)

    assert first.status_code == retry.status_code == 502
    assert first.json() == retry.json()
    store: InMemoryStore = app.state.store
    assert store.load_conversation(first.json()["conversation_id"]) == ()
    assert len(model.calls) == 1


async def test_chat_follow_up_can_reuse_saved_research(
    make_article: Callable[[str], ArticleRecord],
) -> None:
    """Use the saved event and passages to answer an existing conversation's follow-up."""
    article: ArticleRecord = make_article("npr")
    brief: ResearchBrief = ResearchBrief.model_validate({
        "status": "clear", "event": "Earthquake rescue",
        "start_date": "2026-11-07", "end_date": "2026-11-08",
    })
    findings: ResearcherFindings = ResearcherFindings.model_validate({
        "group": "liberal", "article_ids": [str(article.article_id)],
        "main_focuses": [], "limitations": [],
    })

    def reply(call: ModelCall) -> ToolCalls | FinalOutput:
        """Use the Writer directly for the stored research and cite a saved passage."""
        if "You are the Writer" in call.system_instructions:
            assert article.passages[0].passage_id in call.input_text
            return FinalOutput({"summary": [{
                "text": "NPR reported on the rescue response.",
                "passage_ids": [article.passages[0].passage_id],
            }]})
        assert "Earthquake rescue" in call.system_instructions
        if not call.tool_results:
            return ToolCalls([("write_answer", {"question": "What did NPR report?", "alignment": []})])
        return FinalOutput({"brief": brief.model_dump(mode="json")})

    model: ScriptedModel = ScriptedModel(reply)
    app = build_app(Settings(), model)
    store: InMemoryStore = app.state.store
    first_request: ChatRequest = ChatRequest.model_validate({
        "conversation_id": None, "request_id": "initial",
        "messages": [{"role": "user", "content": "Compare earthquake coverage."}],
    })
    record, _ = store.begin_request(first_request)
    store.save_article(record.conversation_id, article)
    store.save_research(record.conversation_id, brief, (findings,))
    store.complete_request(ChatResponse(
        conversation_id=record.conversation_id, request_id=first_request.request_id,
        answer="Here is the available coverage.", tool_calls=[],
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response: Response = await client.post("/chat", json={
            "conversation_id": record.conversation_id, "request_id": "follow-up",
            "messages": [
                {"role": "user", "content": "Compare earthquake coverage."},
                {"role": "assistant", "content": "Here is the available coverage."},
                {"role": "user", "content": "What did NPR report?"},
            ],
        })

    assert response.status_code == 200
    assert response.json()["conversation_id"] == record.conversation_id
    assert article.canonical_url in response.json()["answer"]
    assert "Paragraph 1" in response.json()["answer"]
    assert [call["tool"] for call in response.json()["tool_calls"]] == ["write_answer"]
