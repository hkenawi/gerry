"""
Composition root: the one place where concrete parts are assembled.

Components receive narrow dependencies from here instead of creating global
clients, so tests can inject fakes and no provider is contacted at startup.
"""

from fastapi import FastAPI
from agents import ModelSettings
from agents.extensions.models.litellm_model import LitellmModel

from backend.application.settings import Settings
from backend.sources.service import ArticleSourceService
from backend.sources.access.http import SourceLimits
from backend.interfaces.http.app import create_http_app
from backend.infrastructure.persistence import InMemoryStore


def build_app(settings: Settings, model: object) -> FastAPI:
    """
    Assemble the HTTP application from validated settings and an injected model.
    """
    app = create_http_app()
    app.state.settings = settings
    app.state.model = model
    app.state.model_settings = build_model_settings(settings)
    store: InMemoryStore = InMemoryStore()
    app.state.store = store
    # The application owns and counts retries, so the source layer must not retry.
    app.state.sources = ArticleSourceService(store, limits=SourceLimits(max_retries=0))
    return app


def build_litellm_model(settings: Settings) -> LitellmModel:
    """
    Create the real Gemini-backed model; building it makes no network call.
    """
    return LitellmModel(model=settings.model_name, api_key=settings.api_key)


def build_model_settings(settings: Settings) -> ModelSettings:
    """Forward Vertex configuration and leave retry ownership with application code."""
    extra_args: dict[str, str | int] = {
        "vertex_location": settings.vertex_location,
        "num_retries": 0,
    }
    if settings.vertex_project:
        extra_args["vertex_project"] = settings.vertex_project
    return ModelSettings(
        include_usage=True,
        max_tokens=settings.max_output_tokens,
        extra_args=extra_args,
    )
