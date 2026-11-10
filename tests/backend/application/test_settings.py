"""
Behavior tests for loading typed application settings from the environment.

Tests supply explicit environment mappings to exercise defaults and overrides
without depending on local credentials or process state."""

import pytest

from backend.application.settings import (
    Settings,
    load_settings,
    ConfigurationError,
)


def test_default_model_matches_bibs_and_uses_google_credentials() -> None:
    """Use the chosen Vertex model without requiring a Gemini API key."""
    settings: Settings = load_settings({})

    assert settings.model_name == "vertex_ai/gemini-3.5-flash-lite"
    assert settings.vertex_location == "global"
    assert settings.api_key is None
    assert settings.max_lead_turns == 8
    assert settings.max_research_rounds == 3
    assert settings.max_article_reads == 30
    assert settings.max_concurrent_researchers == 2
    assert settings.request_deadline_seconds == 300
    assert settings.max_retries == 2


def test_ceilings_can_be_overridden_from_the_environment() -> None:
    """
    Operators can tune ceilings without changing code.
    """
    settings: Settings = load_settings(
        {
            "GERRY_MODEL": "m",
            "GEMINI_API_KEY": "k",
            "GERRY_MAX_RETRIES": "5",
            "GERRY_REQUEST_DEADLINE_SECONDS": "60",
            "GERRY_MAX_SEARCH_CALLS": "6",
            "GERRY_MAX_MODEL_CALLS": "12",
            "GERRY_MAX_OUTPUT_TOKENS": "2048",
        }
    )

    assert settings.max_retries == 5
    assert settings.request_deadline_seconds == 60
    assert settings.max_lead_turns == 8
    assert settings.max_search_calls == 6
    assert settings.max_model_calls == 12
    assert settings.max_output_tokens == 2048


@pytest.mark.parametrize("bad_value", ["0", "many"])
def test_invalid_ceiling_is_rejected_without_echoing_the_value(
    bad_value: str,
) -> None:
    """
    A ceiling must be a positive integer; the error names the variable only.
    """
    with pytest.raises(ConfigurationError) as error:
        load_settings(
            {
                "GERRY_MODEL": "m",
                "GEMINI_API_KEY": "k",
                "GERRY_MAX_LEAD_TURNS": bad_value,
            }
        )

    assert "GERRY_MAX_LEAD_TURNS" in str(error.value)
    assert bad_value not in str(error.value)
