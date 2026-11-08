"""Load typed runtime settings without contacting a provider.

Settings are read from an explicit mapping rather than the global environment so
that configuration is testable. Failures name the offending variable but never
include its value, so secrets cannot leak into logs or error messages. The default
model and Google credential setup match the user's bibs project."""

from enum import StrEnum
from typing import Mapping
from dataclasses import dataclass


class EnvironmentVariable(StrEnum):
    """
    Names of the environment variables the application reads.
    """

    MODEL = "GERRY_MODEL"
    API_KEY = "GEMINI_API_KEY"
    VERTEX_PROJECT = "GOOGLE_CLOUD_PROJECT"
    VERTEX_LOCATION = "GOOGLE_CLOUD_LOCATION"
    MAX_LEAD_TURNS = "GERRY_MAX_LEAD_TURNS"
    MAX_RESEARCH_ROUNDS = "GERRY_MAX_RESEARCH_ROUNDS"
    MAX_ARTICLE_READS = "GERRY_MAX_ARTICLE_READS"
    MAX_CONCURRENT_RESEARCHERS = "GERRY_MAX_CONCURRENT_RESEARCHERS"
    REQUEST_DEADLINE_SECONDS = "GERRY_REQUEST_DEADLINE_SECONDS"
    MAX_RETRIES = "GERRY_MAX_RETRIES"
    MAX_SEARCH_CALLS = "GERRY_MAX_SEARCH_CALLS"
    MAX_MODEL_CALLS = "GERRY_MAX_MODEL_CALLS"
    MAX_OUTPUT_TOKENS = "GERRY_MAX_OUTPUT_TOKENS"


class ConfigurationError(Exception):
    """
    Raised at startup when required configuration is missing or invalid.
    """


class GeminiSetting(StrEnum):
    """Keep the selected provider/model vocabulary in one place."""

    MODEL = "vertex_ai/gemini-3.5-flash-lite"
    LOCATION = "global"
    PREFIX = "vertex_ai/"


@dataclass(frozen=True)
class SettingsConstants:
    """Expose typed environment and Gemini constants to configuration consumers."""

    environment: type[EnvironmentVariable] = EnvironmentVariable
    gemini: type[GeminiSetting] = GeminiSetting


SETTINGS_CONSTANTS: SettingsConstants = SettingsConstants()


@dataclass(frozen=True)
class Settings:
    """
    Validated application settings.
    """

    model_name: str = SETTINGS_CONSTANTS.gemini.MODEL.value
    api_key: str | None = None
    vertex_project: str | None = None
    vertex_location: str = SETTINGS_CONSTANTS.gemini.LOCATION.value
    max_lead_turns: int = 8
    max_research_rounds: int = 3
    max_article_reads: int = 30
    max_concurrent_researchers: int = 2
    request_deadline_seconds: int = 300
    max_retries: int = 2
    max_search_calls: int = 20
    max_model_calls: int = 40
    max_output_tokens: int = 4096


def load_settings(environ: Mapping[str, str]) -> Settings:
    """
    Build settings from a mapping, raising an actionable error if invalid.
    """
    defaults: Settings = Settings()
    model_name: str = environ.get(
        SETTINGS_CONSTANTS.environment.MODEL.value, defaults.model_name,
    ).strip()
    api_key: str | None = environ.get(
        SETTINGS_CONSTANTS.environment.API_KEY.value, "",
    ).strip() or None
    if not model_name:
        raise ConfigurationError("GERRY_MODEL must not be blank.")
    if not model_name.startswith(SETTINGS_CONSTANTS.gemini.PREFIX.value) and not api_key:
        raise ConfigurationError("Missing required environment variable GEMINI_API_KEY.")
    return Settings(
        model_name=model_name,
        api_key=api_key,
        vertex_project=environ.get(
            SETTINGS_CONSTANTS.environment.VERTEX_PROJECT.value, "",
        ).strip() or None,
        vertex_location=environ.get(
            SETTINGS_CONSTANTS.environment.VERTEX_LOCATION.value,
            defaults.vertex_location,
        ).strip() or defaults.vertex_location,
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
        max_search_calls=read_ceiling(
            environ, SETTINGS_CONSTANTS.environment.MAX_SEARCH_CALLS,
            defaults.max_search_calls,
        ),
        max_model_calls=read_ceiling(
            environ, SETTINGS_CONSTANTS.environment.MAX_MODEL_CALLS,
            defaults.max_model_calls,
        ),
        max_output_tokens=read_ceiling(
            environ, SETTINGS_CONSTANTS.environment.MAX_OUTPUT_TOKENS,
            defaults.max_output_tokens,
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
