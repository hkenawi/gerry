"""Keep prototype conversations, request results, and evidence in process memory.

One lock protects request claims and writes. Callers must finish or interrupt each
claimed request. State is deliberately lost when the backend process exits."""

from enum import StrEnum
from copy import deepcopy
from uuid import UUID, uuid4
from _thread import LockType
from threading import Lock
from dataclasses import dataclass, replace

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


class InMemoryStore:
    """Own authoritative state for one backend process without external services."""

    def __init__(self) -> None:
        """Create empty state and the lock used to claim and finish turns."""
        self._lock: LockType = Lock()
        self._requests: dict[str, RequestRecord] = {}
        self._conversations: dict[str, tuple[ChatMessage, ...]] = {}
        self._articles: dict[str, dict[UUID, ArticleRecord]] = {}
        self._research: dict[
            str, tuple[ResearchBrief, tuple[ResearcherFindings, ...]]
        ] = {}

    def begin_request(self, request: ChatRequest) -> tuple[RequestRecord, bool]:
        """Return a request record and whether the caller owns new work."""
        with self._lock:
            existing: RequestRecord | None = self._requests.get(request.request_id)
            if existing is not None:
                if existing.request != request:
                    raise RequestConflict("Request ID was used with another payload.")
                return deepcopy(existing), False
            conversation_id: str = request.conversation_id or str(uuid4())
            history: tuple[ChatMessage, ...] = (
                self._conversations[conversation_id]
                if request.conversation_id is not None else ()
            )
            if tuple(request.messages[:-1]) != history:
                raise RequestConflict("Submitted history does not match saved history.")
            if any(
                record.conversation_id == conversation_id
                and record.status is PERSISTENCE_CONSTANTS.statuses.RUNNING
                for record in self._requests.values()
            ):
                raise RequestConflict("Another turn is running in this conversation.")
            self._conversations.setdefault(conversation_id, ())
            self._articles.setdefault(conversation_id, {})
            record: RequestRecord = RequestRecord(
                request=deepcopy(request), conversation_id=conversation_id,
            )
            self._requests[request.request_id] = record
            return deepcopy(record), True

    def load_conversation(self, conversation_id: str) -> tuple[ChatMessage, ...]:
        """Return a detached visible history or raise KeyError if state is gone."""
        with self._lock:
            return deepcopy(self._conversations[conversation_id])

    def interrupt_request(self, request_id: str) -> None:
        """Mark cancelled work explicitly without modifying completed messages."""
        with self._lock:
            record: RequestRecord = self._requests[request_id]
            if record.status is not PERSISTENCE_CONSTANTS.statuses.RUNNING:
                raise RequestConflict("Only a running request can be interrupted.")
            self._requests[request_id] = replace(
                record, status=PERSISTENCE_CONSTANTS.statuses.INTERRUPTED,
            )

    def complete_request(self, response: ChatResponse) -> None:
        """Save a completed response and append its visible exchange atomically."""
        with self._lock:
            record: RequestRecord = self._requests[response.request_id]
            if record.status is not PERSISTENCE_CONSTANTS.statuses.RUNNING:
                raise RequestConflict("Only a running request can be completed.")
            if record.conversation_id != response.conversation_id:
                raise RequestConflict("Response belongs to another conversation.")
            self._conversations[record.conversation_id] += (
                deepcopy(record.request.messages[-1]),
                ChatMessage(role=CHAT_CONSTANTS.roles.ASSISTANT, content=response.answer),
            )
            self._requests[response.request_id] = replace(
                record,
                status=PERSISTENCE_CONSTANTS.statuses.COMPLETED,
                response=deepcopy(response),
            )

    def save_article(
        self, conversation_id: str, article: ArticleRecord,
    ) -> ArticleRecord:
        """Save immutable evidence for an existing conversation and return it."""
        with self._lock:
            articles: dict[UUID, ArticleRecord] = self._articles[conversation_id]
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
            return self._articles[conversation_id][article_id]

    def list_articles(self, conversation_id: str) -> tuple[ArticleRecord, ...]:
        """List immutable snapshots collected in this conversation only."""
        with self._lock:
            return tuple(self._articles[conversation_id].values())

    def save_research(
        self,
        conversation_id: str,
        brief: ResearchBrief,
        findings: tuple[ResearcherFindings, ...],
    ) -> None:
        """Save a detached research brief and findings for an existing session."""
        with self._lock:
            if conversation_id not in self._conversations:
                raise KeyError(conversation_id)
            self._research[conversation_id] = deepcopy((brief, findings))

    def load_research(
        self, conversation_id: str,
    ) -> tuple[ResearchBrief, tuple[ResearcherFindings, ...]]:
        """Return detached research state without permitting mutation of storage."""
        with self._lock:
            return deepcopy(self._research[conversation_id])
