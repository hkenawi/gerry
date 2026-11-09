"""
A scripted model for offline agent tests.

``ScriptedModel`` implements the Agents SDK ``Model`` interface so that real
agents, tools, and the SDK runner execute end to end while the "model" replies
come from a test-supplied handler. No provider or network is ever contacted.
"""

import json
from uuid import uuid4
from dataclasses import dataclass
from typing import Any, Callable, Awaitable, AsyncIterator

from agents import Usage, ModelResponse
from agents.models.interface import Model
from openai.types.responses import (
    ResponseOutputText,
    ResponseOutputMessage,
    ResponseFunctionToolCall,
)


@dataclass(frozen=True)
class ModelCall:
    """
    What the agent sent to the model on one turn.
    """

    system_instructions: str
    input_items: list[dict[str, Any]]
    tool_names: tuple[str, ...]

    @property
    def input_text(self) -> str:
        """
        Return the whole conversation so far as one searchable string.
        """
        return json.dumps(self.input_items, default=str)

    @property
    def tool_results(self) -> list[str]:
        """
        Return the outputs of tools already called in this run, oldest first.
        """
        return [
            str(item.get("output"))
            for item in self.input_items
            if item.get("type") == "function_call_output"
        ]


@dataclass(frozen=True)
class ToolCalls:
    """
    A model reply that calls one or more tools in the same turn.
    """

    calls: list[tuple[str, dict[str, Any]]]


@dataclass(frozen=True)
class FinalOutput:
    """
    A model reply that ends the run with structured JSON output.
    """

    payload: dict[str, Any]


Reply = ToolCalls | FinalOutput
Handler = Callable[[ModelCall], Reply | Awaitable[Reply]]


class ScriptedModel(Model):
    """
    A model whose replies are produced by a handler function.
    """

    def __init__(self, handler: Handler) -> None:
        """
        Remember the handler and start with no recorded calls.
        """
        self._handler: Handler = handler
        self.calls: list[ModelCall] = []

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        prompt: Any = None,
    ) -> ModelResponse:
        """
        Ask the handler for a reply and convert it to SDK output items.
        """
        items: list[dict[str, Any]] = (
            [{"role": "user", "content": input}]
            if isinstance(input, str)
            else [dict(item) for item in input]
        )
        call: ModelCall = ModelCall(
            system_instructions=system_instructions or "",
            input_items=items,
            tool_names=tuple(getattr(tool, "name", "") for tool in tools),
        )
        self.calls.append(call)
        reply: Reply | Awaitable[Reply] = self._handler(call)
        if hasattr(reply, "__await__"):
            reply = await reply  # type: ignore[misc]
        return ModelResponse(
            output=self._build_output(reply),  # type: ignore[arg-type]
            usage=Usage(),
            response_id=None,
        )

    @staticmethod
    def _build_output(reply: Reply) -> list[Any]:
        """
        Convert a scripted reply into Responses API output items.
        """
        if isinstance(reply, ToolCalls):
            return [
                ResponseFunctionToolCall(
                    arguments=json.dumps(arguments),
                    call_id=f"call_{uuid4().hex}",
                    name=name,
                    type="function_call",
                )
                for name, arguments in reply.calls
            ]
        return [
            ResponseOutputMessage(
                id=f"msg_{uuid4().hex}",
                content=[
                    ResponseOutputText(
                        annotations=[],
                        text=json.dumps(reply.payload),
                        type="output_text",
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            )
        ]

    def stream_response(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        """
        Streaming is not used by the application and is not scripted.
        """
        raise NotImplementedError("ScriptedModel does not support streaming.")
