"""Expose the research workflow and live progress through FastAPI.

The application factory receives process-local storage and model dependencies.
HTTP retries reuse claimed requests, and the progress stream observes work
owned by POST /chat."""

import time
import asyncio
import logging

from pathlib import Path
from agents import ModelSettings
from datetime import UTC, datetime
from fastapi import FastAPI, Request
from agents.models.interface import Model
from collections.abc import AsyncIterator
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from backend.application.settings import Settings
from backend.application.turn.run_turn import TurnResult, run_turn
from backend.interfaces.http.chat_contracts import ChatRequest, ChatResponse
from backend.application.turn.tool_calls import ToolCallOutcome, ToolCallRecord
from backend.application.turn.request_state import (
    RequestState,
    SourceGateway,
    build_request_state,
)
from backend.interfaces.http.progress_event import (
    ProgressEvent,
    ProgressEventType,
    format_sse_frame,
)
from backend.application.turn.failure_category import (
    FailureCategory,
    FailureDescription,
    describe_failure,
)
from backend.infrastructure.persistence.memory import (
    PERSISTENCE_CONSTANTS,
    InMemoryStore,
    RequestConflict,
    RequestRecord,
    RequestStatus,
)


logger: logging.Logger = logging.getLogger(__name__)
FRONTEND_DIRECTORY: Path = Path(__file__).resolve().parents[3] / "frontend"


def respond_to_chat(
    response: ChatResponse,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Serialize the same four-field envelope for success and handled failure."""
    return JSONResponse(response.model_dump(mode="json"), status_code, headers)


def reject_chat(
    conversation_id: str | None,
    request_id: str,
    answer: str,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Return a safe error while echoing available request identifiers."""
    return respond_to_chat(ChatResponse(
        conversation_id=conversation_id or "", request_id=request_id,
        answer=answer, tool_calls=[],
    ), status_code, headers)


def create_http_app(
    settings: Settings,
    model: Model,
    store: InMemoryStore,
    sources: SourceGateway,
    model_settings: ModelSettings | None = None,
) -> FastAPI:
    """Serve the browser UI and connect chat to the shared workflow and store."""
    app: FastAPI = FastAPI(title="Gerry")
    progress: dict[str, list[ProgressEvent]] = {}
    app.mount("/static", StaticFiles(directory=FRONTEND_DIRECTORY / "static"))

    @app.get("/", include_in_schema=False)
    async def serve_home() -> FileResponse:
        """Return the chat page without making a model call."""
        return FileResponse(FRONTEND_DIRECTORY / "index.html")

    @app.exception_handler(RequestValidationError)
    async def reject_invalid_request(
        request: Request, error: RequestValidationError,
    ) -> JSONResponse:
        """Report invalid chat input without returning the submitted body."""
        body: object = error.body
        conversation_id: object = body.get("conversation_id") if isinstance(body, dict) else None
        request_id: object = body.get("request_id") if isinstance(body, dict) else None
        return reject_chat(
            conversation_id if isinstance(conversation_id, str) else None,
            request_id if isinstance(request_id, str) else "",
            "The chat request is invalid. Check the message and try again.",
            422,
        )

    @app.get("/health")
    async def report_health() -> dict[str, str]:
        """Report that the backend can receive requests."""
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    async def handle_chat(request: ChatRequest) -> JSONResponse:
        """Claim a turn, run it once, and save its final response for retries."""
        record: RequestRecord
        claimed: bool
        try:
            record, claimed = store.begin_request(request)
        except KeyError:
            return reject_chat(
                request.conversation_id, request.request_id,
                "This conversation has expired. Start a new chat to continue.", 404,
            )
        except RequestConflict as error:
            return reject_chat(request.conversation_id, request.request_id, str(error), 409)
        if not claimed:
            if record.response is not None:
                return respond_to_chat(record.response, record.response_status)
            if record.status is PERSISTENCE_CONSTANTS.statuses.RUNNING:
                return reject_chat(
                    record.conversation_id, request.request_id,
                    "Gerry is still working on this request. Try again shortly.",
                    409, {"Retry-After": "1"},
                )
            return reject_chat(
                record.conversation_id, request.request_id,
                "This request was interrupted. Send the message again to restart it.", 409,
            )

        events: list[ProgressEvent] = []
        progress[request.request_id] = events

        def publish(event_type: ProgressEventType, agent: str, message: str) -> None:
            """Append progress observed during this turn."""
            events.append(ProgressEvent(
                type=event_type, agent=agent, message=message, timestamp=datetime.now(UTC),
            ))

        def report_tool(call: ToolCallRecord) -> None:
            """Publish a progress update when a recorded tool call ends."""
            action: str = call.tool.replace("_", " ")
            message: str = (
                f"Finished {action}." if call.outcome is ToolCallOutcome.SUCCESS
                else f"Could not complete {action}."
            )
            publish(ProgressEventType.TOOL_FINISHED, call.agent, message)

        state: RequestState | None = None
        try:
            state = build_request_state(
                record.conversation_id, settings, store, sources, on_tool_record=report_tool,
            )
            publish(ProgressEventType.AGENT_STARTED, "lead", "Reviewing your question.")
            result: TurnResult = await run_turn(request.messages, state, model, model_settings)
        except asyncio.CancelledError:
            store.interrupt_request(request.request_id)
            raise
        except Exception as error:
            logger.error("Chat request %r failed (%s).", request.request_id, type(error).__name__)
            result = TurnResult(
                describe_failure(FailureCategory.UNEXPECTED).message,
                state.recorder.records if state is not None else (),
                FailureCategory.UNEXPECTED,
            )
        if not result.answer.strip():
            result = TurnResult(
                describe_failure(FailureCategory.INVALID_OUTPUT).message,
                result.tool_calls,
                FailureCategory.INVALID_OUTPUT,
            )
        status_code: int = describe_failure(result.failure).http_status if result.failure else 200
        response: ChatResponse = ChatResponse(
            conversation_id=record.conversation_id, request_id=request.request_id,
            answer=result.answer, tool_calls=list(result.tool_calls),
        )
        publish(ProgressEventType.AGENT_FINISHED, "lead", "Finished reviewing your request.")
        try:
            store.complete_request(response, status_code)
        except Exception as error:
            logger.error("Chat request %r could not be saved (%s).", request.request_id, type(error).__name__)
            if store.request_status(request.request_id) is PERSISTENCE_CONSTANTS.statuses.RUNNING:
                store.interrupt_request(request.request_id)
            failure: FailureDescription = describe_failure(FailureCategory.PERSISTENCE_FAILURE)
            return respond_to_chat(
                response.model_copy(update={"answer": failure.message}), failure.http_status,
            )
        return respond_to_chat(response, status_code)

    @app.get("/chat/progress/{request_id}")
    async def stream_progress(request_id: str, request: Request) -> StreamingResponse:
        """Replay progress and stream new events while the corresponding turn runs."""
        last_event_id: str = request.headers.get("last-event-id", "")
        offset: int = int(last_event_id) if last_event_id.isdecimal() and len(last_event_id) < 12 else 0

        async def iterate_events() -> AsyncIterator[str]:
            """Wait briefly for POST to claim the turn and stop when it finishes."""
            cursor: int = offset
            claim_deadline: float = time.monotonic() + 5.0
            while True:
                events: list[ProgressEvent] = progress.get(request_id, [])
                while cursor < len(events):
                    event: ProgressEvent = events[cursor]
                    cursor += 1
                    yield f"id: {cursor}\n{format_sse_frame(event)}"
                status: RequestStatus | None = store.request_status(request_id)
                if status in (
                    PERSISTENCE_CONSTANTS.statuses.COMPLETED,
                    PERSISTENCE_CONSTANTS.statuses.INTERRUPTED,
                ) or (status is None and time.monotonic() >= claim_deadline):
                    return
                await asyncio.sleep(0.15)

        return StreamingResponse(
            iterate_events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
