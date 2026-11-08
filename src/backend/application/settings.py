"""
Typed application settings loaded from environment variables.

Settings are read from an explicit mapping rather than the global environment so
that configuration is testable. Failures name the offending variable but never
include its value, so secrets cannot leak into logs or error messages.
"""

from enum import StrEnum
from typing import Mapping
from dataclasses import dataclass


class EnvironmentVariable(StrEnum):
    """
    Names of the environment variables the application reads.
    """

    MODEL = "GERRY_MODEL"
    API_KEY = "GEMINI_API_KEY"
    MAX_LEAD_TURNS = "GERRY_MAX_LEAD_TURNS"
    MAX_RESEARCH_ROUNDS = "GERRY_MAX_RESEARCH_ROUNDS"
    MAX_ARTICLE_READS = "GERRY_MAX_ARTICLE_READS"
    MAX_CONCURRENT_RESEARCHERS = "GERRY_MAX_CONCURRENT_RESEARCHERS"
    REQUEST_DEADLINE_SECONDS = "GERRY_REQUEST_DEADLINE_SECONDS"
    MAX_RETRIES = "GERRY_MAX_RETRIES"


class ConfigurationError(Exception):
    """
    Raised at startup when required configuration is missing or invalid.
    """


@dataclass(frozen=True)
class Settings:
    """
    Validated application settings.
    """

    model_name: str
    api_key: str
    max_lead_turns: int = 8
    max_research_rounds: int = 3
    max_article_reads: int = 30
    max_concurrent_researchers: int = 2
    request_deadline_seconds: int = 300
    max_retries: int = 2


def load_settings(environ: Mapping[str, str]) -> Settings:
    """
    Build settings from a mapping, raising an actionable error if invalid.
    """
    values: dict[EnvironmentVariable, str] = {}
    for variable in (EnvironmentVariable.MODEL, EnvironmentVariable.API_KEY):
        value = environ.get(variable.value, "").strip()
        if not value:
            raise ConfigurationError(
                f"Missing required environment variable {variable.value}."
            )
        values[variable] = value
    defaults = Settings(model_name="", api_key="")
    return Settings(
        model_name=values[EnvironmentVariable.MODEL],
        api_key=values[EnvironmentVariable.API_KEY],
        max_lead_turns=read_ceiling(
            environ, EnvironmentVariable.MAX_LEAD_TURNS, defaults.max_lead_turns
        ),
        max_research_rounds=read_ceiling(
            environ,
            EnvironmentVariable.MAX_RESEARCH_ROUNDS,
            defaults.max_research_rounds,
        ),
        max_article_reads=read_ceiling(
            environ, EnvironmentVariable.MAX_ARTICLE_READS, defaults.max_article_reads
        ),
        max_concurrent_researchers=read_ceiling(
            environ,
            EnvironmentVariable.MAX_CONCURRENT_RESEARCHERS,
            defaults.max_concurrent_researchers,
        ),
        request_deadline_seconds=read_ceiling(
            environ,
            EnvironmentVariable.REQUEST_DEADLINE_SECONDS,
            defaults.request_deadline_seconds,
        ),
        max_retries=read_ceiling(
            environ, EnvironmentVariable.MAX_RETRIES, defaults.max_retries
        ),
    )


def read_ceiling(
    environ: Mapping[str, str],
    variable: EnvironmentVariable,
    default: int,
) -> int:
    """
    Read one integer ceiling from the mapping, falling back to its default.
    """
    raw_value = environ.get(variable.value)
    if raw_value is None:
        return default
    try:
        ceiling = int(raw_value)
    except ValueError:
        ceiling = 0
    if ceiling < 1:
        raise ConfigurationError(
            f"Environment variable {variable.value} must be a positive integer."
        )
    return ceiling
