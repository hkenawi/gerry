# gerry
A political agent who puts bias aside 

## Running the backend

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). If the repo is inside
OneDrive, `pyproject.toml` already sets `link-mode = "copy"` for `uv`.

```bash
uv sync
export GERRY_MODEL="gemini/<model-name>"   # see .env.example
export GEMINI_API_KEY="<your key>"
uv run python main.py                       # serves on port 8080
curl http://localhost:8080/health
```

Run the tests (offline, no model or network): `uv run pytest`.
Live tests are opt-in: `uv run pytest -o addopts="" -m live` (the override
replaces the default filter that skips them).
