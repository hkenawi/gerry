"""
Behavior tests for loading typed application settings from the environment.

Settings are loaded from an explicit mapping so tests never touch real
environment variables or credentials.
"""

import pytest

from backend.application.settings import ConfigurationError, load_settings


def test_missing_model_name_raises_error_naming_the_variable() -> None:
    """
    Startup must fail clearly, naming the missing variable.
    """
    with pytest.raises(ConfigurationError) as error:
        load_settings({"GEMINI_API_KEY": "key-value-123"})

    assert "GERRY_MODEL" in str(error.value)


def test_research_ceilings_default_to_agreed_placeholder_values() -> None:
    """
    Without overrides, the agreed placeholder ceilings apply.
    """
    settings = load_settings({"GERRY_MODEL": "m", "GEMINI_API_KEY": "k"})

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
    settings = load_settings(
        {
            "GERRY_MODEL": "m",
            "GEMINI_API_KEY": "k",
            "GERRY_MAX_RETRIES": "5",
            "GERRY_REQUEST_DEADLINE_SECONDS": "60",
        }
    )

    assert settings.max_retries == 5
    assert settings.request_deadline_seconds == 60
    assert settings.max_lead_turns == 8


@pytest.mark.parametrize("bad_value", ["0", "-3", "many"])
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
