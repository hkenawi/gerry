# Gerry the Manderer

## Table of contents

- [Project description](#project-description)
- [Repository structure](#repository-structure)
- [Tools](#tools)
- [Run locally](#run-locally)
- [Sample queries](#sample-queries)

## Project description

Gerry the Manderer is a chatbot for readers who want to see how liberal and
conservative U.S. news outlets cover the same international story. Give it an
event and a date range, or ask it to suggest recent headlines. Gerry searches
a fixed list of ten outlets, including NPR, NBC News, Fox News, and the New York
Post. It compares what the sampled articles emphasize and where they overlap,
with citations you can open to read the supporting excerpts.

## Repository structure

```text
gerry/
├── main.py                  # Local server entry point
├── src/
│   ├── backend/
│   │   ├── agents/          # Lead, liberal and conservative Researchers, and Writer
│   │   ├── application/     # Chat workflow, evidence validation, and answer rendering
│   │   ├── infrastructure/  # In-memory conversation and research storage
│   │   ├── interfaces/http/ # FastAPI routes and request/response schemas
│   │   └── sources/         # Outlet roster, feed and archive search, article extraction
│   └── frontend/           # Browser chat, story picker, and citation viewer
├── tests/                   # Agent, source, and HTTP tests
├── .env.example             # Runtime settings reference
├── pyproject.toml           # Python project configuration
└── uv.lock                  # Locked dependency versions
```

## Tools

- **`search_recent_events`** finds dated headlines so readers can choose a story to compare.
- **`research_liberal_coverage`** runs a researcher on the liberal outlet group for a given event and date range.
- **`research_conservative_coverage`** runs a researcher on the conservative outlet group for the same event and date range.
- **`search_articles`** finds candidate articles in the researcher's assigned outlet feeds and available archives.
- **`read_article`** fetches and extracts the article text used as evidence.
- **`write_answer`** turns the findings into a side-by-side briefing or a detailed report with citations.

## Run locally

Install Python 3.12 or later, `uv`, and the Google Cloud CLI (`gcloud`). Use a
Google Cloud project with the Vertex AI API enabled and credentials that can
access Gemini. From the repository root, run the following commands with your
project ID in place of `YOUR_PROJECT_ID`.

```sh
uv sync --frozen
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
export LITELLM_LOCAL_MODEL_COST_MAP=True
uv run python main.py
```

Open the [chat interface](http://127.0.0.1:8080) or the
[API explorer](http://127.0.0.1:8080/docs). In the chat, type a question and
select **Compare coverage**, or pick a headline from **Recent stories**. Click
a citation to see its excerpt. Ask follow-up questions in the same chat.

The default model is `vertex_ai/gemini-3.5-flash-lite` in the `global` location
and uses Google Application Default Credentials. Export any optional settings
from [`.env.example`](.env.example) in your shell before startup. Run a single
server process because Gerry stores research for follow-ups in memory.

## Sample queries

Paste any of these into a fresh chat.

1. **Find a story.** “What international stories made headlines in the past
   seven days? Give me a few to choose from.”
2. **Compare coverage.** “How did liberal and conservative U.S. outlets cover
   Ukraine over the past week? Where did they agree, and what did each group
   emphasize?”
3. **Ask for a detailed report.** “Compare U.S. news coverage of NATO over the
   past two weeks. Give me a detailed report on the aspects each group
   emphasized, with article excerpts that support the comparison.”
