"""Verify the new Vertex configuration through its public SDK settings factory.

These checks only construct configuration; model endpoints and Google credentials
are never accessed."""

from backend.application.settings import Settings
from backend.application.composition import build_model_settings


def test_vertex_settings_use_global_location_and_report_usage() -> None:
    """Forward the bibs location and disable hidden provider retries."""
    settings = build_model_settings(Settings())

    assert settings.extra_args == {
        "vertex_location": "global",
        "num_retries": 0,
    }
    assert settings.include_usage is True


def test_model_settings_forward_the_output_ceiling_and_project_override() -> None:
    """Bound individual responses and allow an explicit Google Cloud project."""
    settings = build_model_settings(
        Settings(vertex_project="example-project", max_output_tokens=1024),
    )

    assert settings.max_tokens == 1024
    assert settings.extra_args["vertex_project"] == "example-project"
