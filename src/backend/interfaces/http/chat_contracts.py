"""
Public request and response contracts for the ``POST /chat`` endpoint.

The models here are the single definition of what the frontend sends and
receives. They validate untrusted client input at the HTTP boundary and carry
no agent or storage logic.
"""

from enum import StrEnum
from typing import Self, ClassVar
from dataclasses import dataclass

from pydantic import Field, BaseModel, ConfigDict, model_validator

from backend.application.tool_call_record import ToolCallRecord


class ChatRole(StrEnum):
    """
    Roles a client is allowed to claim for a submitted message.
    """

    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ChatConstants:
    """Expose the allowed client roles and shared request validation settings."""

    roles: type[ChatRole] = ChatRole
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", str_strip_whitespace=True,
    )


CHAT_CONSTANTS: ChatConstants = ChatConstants()


class ChatMessage(BaseModel):
    """
    One message in the conversation history submitted by the client.
    """

    model_config: ClassVar[ConfigDict] = CHAT_CONSTANTS.model_config

    role: ChatRole
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """
    One submitted turn: optional conversation ID, turn ID, and message history.
    """

    model_config: ClassVar[ConfigDict] = CHAT_CONSTANTS.model_config

    conversation_id: str | None = Field(min_length=1)
    request_id: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_message_sequence(self) -> Self:
        """Require alternating visible messages and one final user question."""
        position: int
        message: ChatMessage
        for position, message in enumerate(self.messages):
            expected: ChatRole = (
                CHAT_CONSTANTS.roles.USER
                if position % 2 == 0 else CHAT_CONSTANTS.roles.ASSISTANT
            )
            if message.role is not expected:
                raise ValueError("Messages must alternate user and assistant.")
        if self.messages[-1].role is not CHAT_CONSTANTS.roles.USER:
            raise ValueError("A request must end with a user message.")
        return self


class ChatResponse(BaseModel):
    """
    The four-field response returned for every handled turn, success or failure.
    """

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    request_id: str
    answer: str
    tool_calls: list[ToolCallRecord]
