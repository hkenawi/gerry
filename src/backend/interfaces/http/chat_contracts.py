"""
Public request and response contracts for the ``POST /chat`` endpoint.

The models here are the single definition of what the frontend sends and
receives. They validate untrusted client input at the HTTP boundary and carry
no agent or storage logic.
"""

from enum import StrEnum

from pydantic import Field, BaseModel, ConfigDict

from backend.application.tool_call_record import ToolCallRecord


class ChatRole(StrEnum):
    """
    Roles a client is allowed to claim for a submitted message.
    """

    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    """
    One message in the conversation history submitted by the client.
    """

    role: ChatRole
    content: str


class ChatRequest(BaseModel):
    """
    One submitted turn: optional conversation ID, turn ID, and message history.
    """

    conversation_id: str | None
    request_id: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)


class ChatResponse(BaseModel):
    """
    The four-field response returned for every handled turn, success or failure.
    """

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    request_id: str
    answer: str
    tool_calls: list[ToolCallRecord]
