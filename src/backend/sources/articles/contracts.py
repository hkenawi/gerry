"""Validate immutable article snapshots and their ordered evidence passages.

These records carry collected evidence between sources, persistence, and agents.
They perform no retrieval and do not claim that unknown metadata was verified."""

from uuid import UUID
from datetime import UTC, date, datetime
from typing import Self, ClassVar, Annotated, TypeAlias
from pydantic import (
    Field,
    BaseModel,
    ConfigDict,
    AwareDatetime,
    BeforeValidator,
    field_validator,
    model_validator,
)

from backend.sources.constants import ArticleType, SOURCE_CONSTANTS


def _preserve_publication_date_precision(value: object) -> object:
    """Preserve date precision and reject timestamps with unknown timezones."""
    if isinstance(value, str):
        if len(value) == 10:
            return date.fromisoformat(value)
        value = datetime.fromisoformat(value)
    if isinstance(value, datetime) and value.utcoffset() is None:
        raise ValueError("Publication timestamps require a timezone.")
    return value


PublicationDate: TypeAlias = Annotated[
    datetime | date | None,
    BeforeValidator(_preserve_publication_date_precision),
]


class ArticlePassage(BaseModel):
    """Preserve one nonempty paragraph and its stable citation identifier."""

    model_config: ClassVar[ConfigDict] = SOURCE_CONSTANTS.model_config

    passage_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ArticleRecord(BaseModel):
    """Carry one saved article snapshot with optional publisher metadata."""

    model_config: ClassVar[ConfigDict] = SOURCE_CONSTANTS.model_config

    article_id: UUID
    outlet_id: str = Field(min_length=1)
    requested_url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    bylines: tuple[str, ...] = ()
    published_at: PublicationDate = None
    updated_at: PublicationDate = None
    retrieved_at: AwareDatetime
    article_type: ArticleType = SOURCE_CONSTANTS.article_types.UNKNOWN
    reporting_origin: str | None = None
    syndicated: bool | None = None
    duplicate_of: UUID | None = None
    passages: tuple[ArticlePassage, ...] = Field(min_length=1)

    @field_validator("retrieved_at")
    @classmethod
    def normalize_retrieval_timestamp(cls, value: datetime) -> datetime:
        """Store retrieval time in UTC independently of publication timezone."""
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_passage_references(self) -> Self:
        """Require each reference to identify its snapshot and ordered paragraph."""
        position: int
        passage: ArticlePassage
        for position, passage in enumerate(self.passages, start=1):
            if passage.passage_id != f"{self.article_id}:p{position:04d}":
                raise ValueError("Passage IDs must match the article and paragraph.")
        return self
