"""
Behavior tests for the HTTP application, called in-process with async httpx.

No real server, network, or model provider is involved.
"""

from httpx import AsyncClient, ASGITransport

from backend.interfaces.http.app import create_http_app


def build_client() -> AsyncClient:
    """
    Build an async client that calls the application directly in-process.
    """
    return AsyncClient(
        transport=ASGITransport(app=create_http_app()),
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


async def test_stub_chat_returns_the_four_field_envelope() -> None:
    """
    A valid turn gets a conversation ID, its own request ID, an answer, and calls.
    """
    async with build_client() as client:
        response = await client.post(
            "/chat",
            json={
                "conversation_id": None,
                "request_id": "turn-1",
                "messages": [{"role": "user", "content": "Compare coverage."}],
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"conversation_id", "request_id", "answer", "tool_calls"}
    assert body["request_id"] == "turn-1"
    assert body["conversation_id"] != ""
    assert body["tool_calls"] == []


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
