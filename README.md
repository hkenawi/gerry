# Gerry

Compare how selected liberal and conservative news outlets cover the same
international event, with attribution and supporting evidence.

The backend foundation and React shell are in place. `/chat` currently returns
a placeholder; the research workflow and briefing interface come in later phases.

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
and `/chat` to the backend on port 8080. Starting the shell and checking backend
availability do not invoke a model. Backend and frontend run separately during
development; serving the frontend build from Python belongs to deployment work.

The selected model is `vertex_ai/gemini-3.5-flash-lite` in `global`, matching
`bibs`. Real model calls will require Google Application Default Credentials:

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login
```

See [.env.example](.env.example) for optional environment overrides. Export them
in your shell; the application does not automatically load `.env` files. No
Gemini API key is required for the default Vertex configuration.

Storage is intentionally in memory. Backend restarts lose conversations and
collected evidence; run one backend process. Durable storage is deferred.

## Development commands

```bash
# Backend, from the repository root
LITELLM_LOCAL_MODEL_COST_MAP=True uv run pytest

# Frontend, from src/frontend
npm test
npm run build
```

Frontend build output goes to `src/frontend/dist`. Live backend tests remain
opt-in: `uv run pytest -o addopts="" -m live`. No paid API checks are required
for the foundation or frontend shell.
