# Gerry

Compare how selected liberal and conservative news outlets cover the same
international event, with attribution and supporting evidence.

The local app accepts research questions and follow-ups. It shows progress,
comparison tables, and citations that open the corresponding source excerpts.

## Local development

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 22.12+.

Start the backend from the repository root:

```bash
uv sync --frozen
export LITELLM_LOCAL_MODEL_COST_MAP=True
uv run python main.py
```

Start the frontend in a second terminal:

```bash
cd src/frontend
npm ci
npm run dev
```

Open [Gerry](http://127.0.0.1:5173). The development server forwards `/health`
and `/chat` to the backend on port 8080. Backend and frontend run separately
during development. The page can load before configuring model credentials.

The selected model is `vertex_ai/gemini-3.5-flash-lite` in `global`, matching
`bibs`. Sending a chat message requires Google Application Default Credentials.

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login
```

See [.env.example](.env.example) for optional environment overrides. Export them
in your shell; the application does not automatically load `.env` files. No
Gemini API key is required for the default Vertex configuration.

Chat history stays in browser memory and clears on refresh. The backend keeps
research and completed responses in memory for follow-ups and retries until it
restarts. Run one backend process. After a restart, start a new chat.

## Development commands

```bash
# Backend, from the repository root
LITELLM_LOCAL_MODEL_COST_MAP=True uv run pytest

# Frontend, from src/frontend
npm test
npm run build
```

Frontend build output goes to `src/frontend/dist`. Live backend tests remain
opt-in with `uv run pytest -o addopts="" -m live`. The regular suite uses
scripted model replies and fixture responses.
