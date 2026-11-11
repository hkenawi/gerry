"""Keep prototype conversations, request results, and evidence in process memory.

One lock protects request claims and writes. Callers must finish or interrupt each
claimed request. State is deliberately lost when the backend process exits."""

from enum import StrEnum
from copy import deepcopy
from threading import Lock
from _thread import LockType
from uuid import UUID, uuid4
from dataclasses import dataclass, field, replace

from backend.sources.articles import ArticleRecord
from backend.agents.research_brief import ResearchBrief
from backend.agents.researcher_findings import ResearcherFindings
from backend.interfaces.http.chat_contracts import (
    ChatRequest,
    ChatMessage,
    ChatResponse,
    CHAT_CONSTANTS,
)


class RequestStatus(StrEnum):
    """Distinguish a running request from a completed or interrupted one."""

    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class PersistenceConstants:
    """Expose request lifecycle values without duplicating systemic strings."""

    statuses: type[RequestStatus] = RequestStatus


PERSISTENCE_CONSTANTS: PersistenceConstants = PersistenceConstants()


class RequestConflict(ValueError):
    """Signal incompatible retry payloads, histories, or request transitions."""


@dataclass(frozen=True)
class RequestRecord:
    """Describe a claimed turn and its optional completed response."""

    request: ChatRequest
    conversation_id: str
    status: RequestStatus = PERSISTENCE_CONSTANTS.statuses.RUNNING
    response: ChatResponse | None = None
    response_status: int = 200


@dataclass
class _ConversationState:
    """Group the transcript, evidence, and active turn for one conversation."""

    history: tuple[ChatMessage, ...] = ()
    articles: dict[UUID, ArticleRecord] = field(default_factory=dict)
    research: tuple[ResearchBrief, tuple[ResearcherFindings, ...]] | None = None
    active_request_id: str | None = None


class InMemoryStore:
    """Own authoritative state for one backend process without external services."""

    def __init__(self, max_conversations: int = 100) -> None:
        """Create empty state, the claim lock, and the cap on conversations kept."""
        self._max_conversations: int = max_conversations
        self._lock: LockType = Lock()
        self._requests: dict[str, RequestRecord] = {}
        self._conversations: dict[str, _ConversationState] = {}

    def begin_request(self, request: ChatRequest) -> tuple[RequestRecord, bool]:
        """Return a request record and whether the caller owns new work."""
        with self._lock:
            existing: RequestRecord | None = self._requests.get(request.request_id)
            if existing is not None:
                if existing.request != request:
                    raise RequestConflict("Request ID was used with another payload.")
                return deepcopy(existing), False
            conversation_id: str = request.conversation_id or str(uuid4())
            conversation: _ConversationState = (
                self._conversations[conversation_id]
                if request.conversation_id is not None
                else _ConversationState()
            )
            if tuple(request.messages[:-1]) != conversation.history:
                raise RequestConflict("Submitted history does not match saved history.")
            if conversation.active_request_id is not None:
                raise RequestConflict("Another turn is running in this conversation.")
            record: RequestRecord = RequestRecord(
                request=deepcopy(request),
                conversation_id=conversation_id,
            )
            claimed: RequestRecord = deepcopy(record)
            self._conversations.pop(conversation_id, None)
            self._conversations[conversation_id] = conversation
            conversation.active_request_id = request.request_id
            self._requests[request.request_id] = record
            self._evict_idle_conversations()
            return claimed, True

    def _evict_idle_conversations(self) -> None:
        """Drop the least recently used finished conversations beyond the cap."""
        idle: list[str] = [
            conversation_id for conversation_id, conversation in self._conversations.items()
            if conversation.active_request_id is None
        ]
        for conversation_id in idle[:max(0, len(self._conversations) - self._max_conversations)]:
            del self._conversations[conversation_id]
            self._requests = {
                request_id: record for request_id, record in self._requests.items()
                if record.conversation_id != conversation_id
            }

    def load_conversation(self, conversation_id: str) -> tuple[ChatMessage, ...]:
        """Return a detached visible history or raise KeyError if state is gone."""
        with self._lock:
            return deepcopy(self._conversations[conversation_id].history)

    def interrupt_request(self, request_id: str) -> None:
        """Mark cancelled work explicitly without modifying completed messages."""
        with self._lock:
            record: RequestRecord = self._requests[request_id]
            if record.status is not PERSISTENCE_CONSTANTS.statuses.RUNNING:
                raise RequestConflict("Only a running request can be interrupted.")
            self._requests[request_id] = replace(
                record, status=PERSISTENCE_CONSTANTS.statuses.INTERRUPTED,
            )
            self._conversations[record.conversation_id].active_request_id = None

    def request_status(self, request_id: str) -> RequestStatus | None:
        """Read lifecycle status without copying the request or its answer."""
        with self._lock:
            record: RequestRecord | None = self._requests.get(request_id)
            return record.status if record is not None else None

    def complete_request(self, response: ChatResponse, status_code: int = 200) -> None:
        """Save a completed response and append its visible exchange atomically."""
        with self._lock:
            record: RequestRecord = self._requests[response.request_id]
            if record.status is not PERSISTENCE_CONSTANTS.statuses.RUNNING:
                raise RequestConflict("Only a running request can be completed.")
            if record.conversation_id != response.conversation_id:
                raise RequestConflict("Response belongs to another conversation.")
            conversation: _ConversationState = self._conversations[record.conversation_id]
            completed: RequestRecord = replace(
                record,
                status=PERSISTENCE_CONSTANTS.statuses.COMPLETED,
                response=deepcopy(response),
                response_status=status_code,
            )
            if status_code < 400:
                conversation.history += (
                    deepcopy(record.request.messages[-1]),
                    ChatMessage(role=CHAT_CONSTANTS.roles.ASSISTANT, content=response.answer),
                )
            self._requests[response.request_id] = completed
            conversation.active_request_id = None

    def save_article(
        self, conversation_id: str, article: ArticleRecord,
    ) -> ArticleRecord:
        """Save immutable evidence for an existing conversation and return it."""
        with self._lock:
            articles: dict[UUID, ArticleRecord] = self._conversations[conversation_id].articles
            existing: ArticleRecord | None = articles.get(article.article_id)
            if existing is not None and existing != article:
                raise RequestConflict("A saved snapshot cannot be overwritten.")
            text: str = " ".join(
                " ".join(passage.text for passage in article.passages).split(),
            )
            for saved in articles.values():
                saved_text: str = " ".join(
                    " ".join(passage.text for passage in saved.passages).split(),
                )
                if text != saved_text:
                    continue
                if saved.outlet_id == article.outlet_id and saved.canonical_url == article.canonical_url:
                    return saved
                article = article.model_copy(update={
                    "duplicate_of": saved.duplicate_of or saved.article_id,
                })
                break
            articles[article.article_id] = article
            return article

    def load_article(self, conversation_id: str, article_id: UUID) -> ArticleRecord:
        """Read authorized collected evidence without contacting a source."""
        with self._lock:
            return self._conversations[conversation_id].articles[article_id]

    def list_articles(self, conversation_id: str) -> tuple[ArticleRecord, ...]:
        """List immutable snapshots collected in this conversation only."""
        with self._lock:
            return tuple(self._conversations[conversation_id].articles.values())

    def save_research(
        self,
        conversation_id: str,
        brief: ResearchBrief,
        findings: tuple[ResearcherFindings, ...],
    ) -> None:
        """Save a detached research brief and findings for an existing session."""
        with self._lock:
            conversation: _ConversationState = self._conversations[conversation_id]
            conversation.research = deepcopy((brief, findings))

    def load_research(
        self, conversation_id: str,
    ) -> tuple[ResearchBrief, tuple[ResearcherFindings, ...]]:
        """Return detached research state without permitting mutation of storage."""
        with self._lock:
            research: tuple[ResearchBrief, tuple[ResearcherFindings, ...]] | None = (
                self._conversations[conversation_id].research
            )
            if research is None:
                raise KeyError(conversation_id)
            return deepcopy(research)
