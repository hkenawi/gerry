"""Validate source discovery and access results consumed by agent tools.

Candidates are metadata hints, while article-read results describe saved evidence.
Source outcomes stay separate from application HTTP failures owned by Person A."""

from typing import Self, ClassVar
from pydantic import Field, BaseModel, ConfigDict, model_validator

from backend.sources.articles import ArticleRecord, PublicationDate
from backend.sources.constants import SOURCE_CONSTANTS, SourceAccessStatus


class ArticleCandidate(BaseModel):
    """Describe one discovered URL without claiming its article was read."""

    model_config: ClassVar[ConfigDict] = SOURCE_CONSTANTS.model_config

    outlet_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    snippet: str | None = None
    published_at: PublicationDate = None


class SourceAccessOutcome(BaseModel):
    """Carry one outlet's observed status and optional safe diagnostic detail."""

    model_config: ClassVar[ConfigDict] = SOURCE_CONSTANTS.model_config

    outlet_id: str = Field(min_length=1)
    status: SourceAccessStatus
    url: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    detail: str | None = None


class ArticleSearchResult(BaseModel):
    """Retain candidates and per-outlet outcomes, including partial failures."""

    model_config: ClassVar[ConfigDict] = SOURCE_CONSTANTS.model_config

    candidates: tuple[ArticleCandidate, ...] = ()
    outcomes: tuple[SourceAccessOutcome, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_candidate_outcomes(self) -> Self:
        """Require unambiguous successful discovery for each candidate outlet."""
        statuses: dict[str, SourceAccessStatus] = {
            outcome.outlet_id: outcome.status for outcome in self.outcomes
        }
        if len(statuses) != len(self.outcomes):
            raise ValueError("Search requires one outcome per outlet.")
        success_status: SourceAccessStatus = SOURCE_CONSTANTS.access_statuses.SUCCESS
        if any(
            statuses.get(candidate.outlet_id) is not success_status
            for candidate in self.candidates
        ):
            raise ValueError("Each candidate requires a successful outlet outcome.")
        return self


class ArticleReadResult(BaseModel):
    """Return saved evidence on success or an explicit source failure otherwise.

    The caller must complete persistence before constructing a successful result;
    schema validation cannot establish that a database write actually occurred."""

    model_config: ClassVar[ConfigDict] = SOURCE_CONSTANTS.model_config

    outcome: SourceAccessOutcome
    article: ArticleRecord | None = None

    @model_validator(mode="after")
    def validate_read_evidence(self) -> Self:
        """Require saved evidence exactly when the read reports success."""
        successful: bool = (
            self.outcome.status is SOURCE_CONSTANTS.access_statuses.SUCCESS
        )
        if successful != (self.article is not None):
            raise ValueError("Only a successful read must contain a saved article.")
        if (
            self.article is not None
            and self.article.outlet_id != self.outcome.outlet_id
        ):
            raise ValueError("The saved article must belong to the outcome's outlet.")
        return self
