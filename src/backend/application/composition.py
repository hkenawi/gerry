"""
Composition root: the one place where concrete parts are assembled.

Components receive narrow dependencies from here instead of creating global
clients, so tests can inject fakes and no provider is contacted at startup.
"""

from fastapi import FastAPI
from agents.extensions.models.litellm_model import LitellmModel

from backend.application.settings import Settings
from backend.interfaces.http.app import create_http_app


def build_app(settings: Settings, model: object) -> FastAPI:
    """
    Assemble the HTTP application from validated settings and an injected model.
    """
    app = create_http_app()
    app.state.settings = settings
    app.state.model = model
    return app


def build_litellm_model(settings: Settings) -> LitellmModel:
    """
    Create the real Gemini-backed model; building it makes no network call.
    """
    return LitellmModel(model=settings.model_name, api_key=settings.api_key)
