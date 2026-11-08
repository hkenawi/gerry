"""
FastAPI application exposing the Gerry HTTP interface.

This module only translates HTTP to and from the typed contracts. Agent
workflow, storage, and source access are supplied by the composition root.
"""

from uuid import uuid4

from fastapi import FastAPI

from backend.interfaces.http.chat_contracts import ChatRequest, ChatResponse


def create_http_app() -> FastAPI:
    """
    Create the FastAPI application with its routes registered.
    """
    app = FastAPI(title="Gerry")

    @app.get("/health")
    async def report_health() -> dict[str, str]:
        """
        Report that the application process is running.
        """
        return {"status": "ok"}

    @app.post("/chat")
    async def handle_chat(request: ChatRequest) -> ChatResponse:
        """
        Answer one turn. Placeholder until the agent workflow is connected.
        """
        return ChatResponse(
            conversation_id=request.conversation_id or str(uuid4()),
            request_id=request.request_id,
            answer="Research is not connected yet.",
            tool_calls=[],
        )

    return app
