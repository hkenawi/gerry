"""
Thin entry point that starts the Gerry backend.

All application logic lives under ``src/backend``; this file only reads the
environment, assembles the app, and hands it to the server.
"""

import os
import sys

import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from backend.application.settings import ConfigurationError, load_settings  # noqa: E402
from backend.application.composition import (  # noqa: E402
    build_app,
    build_litellm_model,
)


def main() -> None:
    """
    Load settings, build the app, and serve it, exiting clearly on bad config.
    """
    try:
        settings = load_settings(os.environ)
    except ConfigurationError as error:
        sys.exit(f"Configuration error: {error}")
    app = build_app(settings, build_litellm_model(settings))
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
