# Phase 3: Person A agent workflow

November 8, 2026. The workflow is tested with scripted models, including an
end-to-end test using the real source service and fixture HTTP responses. Live
Gemini and publisher access remain unverified. `/chat` wiring is Phase 4 work.

## What exists

Public entry point: `backend.application.turn.run_turn.run_turn(messages, state, model,
model_settings=None, today=None) -> TurnResult`. It is a plain async function with
no HTTP dependency. `TurnResult` holds `answer` (Markdown string), `tool_calls`
(tuple of `ToolCallRecord`), and `failure` (`FailureCategory | None`).

`state` is a `RequestState` from `build_request_state(conversation_id, settings,
store, sources, clock)`. It is trusted, per-request, and never visible to a model.
It holds the shared budget, the event window, the tool-call recorder, failed reads,
and the validated findings. `sources` is any object matching the `SourceGateway`
protocol (the same three methods as `ArticleSourceService`).

| Piece | Location |
| --- | --- |
| Lead (clarify, fan out, follow up, align) | `src/backend/agents/lead/` |
| Researcher (one definition, both groups) | `src/backend/agents/researcher/` |
| Writer (cited claims, read-only tool), called by the Lead as `write_answer` | `src/backend/agents/writer/` |
| `write_answer` (mode, validation, Writer run, rendering, storage) | `application/answer/write_answer.py` |
| Shared evidence view (articles per group) | `application/evidence/collected_evidence.py` |
| Source tool wrappers (group, window, budget, retries) | `agents/researcher/tools.py` |
| Shared budget | `application/turn/request_budget.py` |
| Run with one correction attempt | `application/turn/structured_run.py` |
| Sample counts and answer mode | `application/answer/sample_assessment.py` |
| Findings checked against saved evidence | `application/evidence/findings_validation.py` |
| Markdown rendering and citation checks | `application/answer/answer_rendering.py` |
| Orchestration | `application/turn/run_turn.py` |

Prompts are Markdown beside each agent (`prompt.md`).

## How a turn runs

1. **Lead** (one run). An unclear event or period ends with a clarifying question.
   Before the SDK runs any initial research tools, a hook requires both group
   calls in the same model response with identical broad briefs. The SDK runs
   each Researcher with a fresh context. The configured concurrency ceiling
   applies per request. Later calls reuse the fixed event and publication window.
2. **Researcher** gets only its assignment (event, group, outlets, window,
   optional focus question). Its tools are trusted wrappers: it supplies a query
   or URL, code supplies the outlets, window and budget. Python checks every
   cited article ID and passage ID against what was saved for that conversation
   and that group, and forces the group field. Invalid findings get one correction
   attempt that continues the same conversation (no repeated reads).
3. **Lead calls `write_answer`** with the reader's question and an aspect
   alignment. The Writer is a tool of the Lead, not a separate stage. Inside the
   tool, code counts the sample per group (`assess_sample`) and decides the mode:
   `comparison`, `summary_only` (one side has zero usable articles), or
   `no_evidence`. The Writer cannot override this.
4. **Writer** (run by the tool) receives the evidence package and returns claims
   with passage IDs. Code validates the alignment and the claims, allows one
   correction, renders the answer, and stores it in `state.final_answer`. The Lead
   gets only a short status message and never sees or edits the rendered text. A
   rejected alignment or report comes back to the Lead as a failure reason it can
   fix. The Writer can also return a specific evidence gap for the Lead to
   follow up on. `write_answer` allows at most 2 Writer attempts per request
   (`MAX_WRITER_CALLS`), within the shared model-call and time limits.
5. **Lead finishes** with a brief only. `LeadOutcome` no longer carries the
   alignment. The Lead's validation rejects a clear brief unless research ran and
   `write_answer` succeeded (one correction attempt, as before).
6. **Fallback.** After a budget, turn, or time limit, `run_turn` can render
   collected headlines and citations directly with a limit note. If there is
   no validated evidence it returns the research-limit failure.

## Rules enforced in code

- One shared budget per request: search calls, article reads, model calls,
  deadline. A "research round" is counted per group (`state.try_start_round`).
- Retries: only `fetch_failed` is retried, up to `max_retries`, and every attempt
  consumes the article-read budget. `composition.py` now builds
  `ArticleSourceService` with `SourceLimits(max_retries=0)` so retries do not stack.
  **This edits your file `composition.py`** (one line plus an import).
- Failed articles never stop a request. Each failure is added to `tool_calls` and
  listed in the answer's Limitations section in plain words.
- Unequal samples are stated, never trimmed ("3 liberal articles from 3 outlets
  and 2 conservative articles from 2 outlets"). Only reporting articles count toward
  the floor of 2 articles from 2 outlets; a side under the floor with at least one
  article is compared and marked thin.
- A side with zero articles gives an objective summary with the reason in plain
  words, and the Writer is rejected if it claims overlap or differences.
- Nothing retrievable on either side gives a plain "no coverage" answer.

## Source-status handling (your `SourceAccessStatus` values)

| Status | Effect |
| --- | --- |
| `success` | Article saved and usable. |
| `fetch_failed` | Retried (shared budget), then reported as a failed article. |
| `paywall`, `access_denied`, `missing_date`, `date_conflict`, `outside_window`, `incomplete_text`, `extraction_failed`, `no_results` | Not retried; article excluded; failure listed in the answer. |
| `storage_failed` | Treated like any failed article today. **Mapping it to `PERSISTENCE_FAILURE` is not done** (Phase 5). |
| `budget_exhausted` | Produced by my wrapper when the shared budget is spent. Research stops; supported findings are written up with a limit note. |

## What the frontend can rely on in `answer`

`answer` is one Markdown string. Sections, when present: `## What the coverage
reports`, `## How the coverage compares` (a table: Aspect, Liberal outlets,
Conservative outlets), `## Where coverage overlaps`, `## Where coverage differs`,
`## Limitations`, `## Sources`. Citations are `[n]` markers pointing at the numbered
Sources list (each line links the canonical URL). A clarification answer is a
plain sentence. Failures use the fixed messages in `failure_category.py`.
`tool_calls[].agent` values: `lead`, `researcher_liberal`, `researcher_conservative`,
`writer`. Tool names: `research_liberal_coverage`, `research_conservative_coverage`,
`write_answer` (agent `lead`), `search_articles`, `read_article`,
`read_collected_article`, `research`.

The frontend `ResearchAnswer` component accepts this Markdown string. It renders
the comparison table and expandable source links. Phase 4 supplies the answer
to `App` after a chat response. The current response carries source links, so
expanding Sources shows the cited articles rather than individual passages.

## Test seams used (agreed in my own words; you waived seam sign-off)

`RequestBudget`, `assess_sample`, `validate_findings`, `GroupSourceTools`,
`render_answer` / `find_report_problems` / `find_alignment_problems`, request-state
round limits, and `run_turn` end to end with a scripted model. Mutation checks:
serializing the researchers fails 5 tests; disabling findings validation fails the
unread-article test.

Test helpers: `tests/backend/conftest.py` (`make_article`, `fake_sources`,
`make_state`) and `tests/support/scripted_model.py` (a `Model` implementation
driven by a handler). `pyproject.toml` now has `pythonpath = ["src", "tests"]`.
You can reuse the scripted model for browser or API tests without a provider.

## Known gaps and honest limits

- **Live model behaviour is unverified.** Tool calling, structured output, and
  concurrent tool calls through LiteLLM and Vertex Gemini have not been run. The
  live spike was parked by the user. This must happen before Phase 4 is signed off.
- **Model or provider outages** (litellm exceptions) are not caught or mapped yet;
  they propagate out of `run_turn`. Phase 5.
- **Follow-up neutrality** ("do not pass the other group's conclusions") is a
  prompt rule. Code cannot verify what the Lead writes in `focus_question`.
- **Time:** the Lead stage uses the remaining shared deadline. The fallback
  renders locally. A blocking source call already in a worker thread may finish
  after the async wait is cancelled.
- Tracing is disabled in every run (`RunConfig(tracing_disabled=True)`) because
  the SDK would otherwise try to export to OpenAI.
- Citation checks prove a passage exists, not that it supports the claim.
- Progress events are defined but not emitted; sessions, idempotency, and the
  `/chat` wiring (`begin_request` / `complete_request`) are Phase 4.

## Change after first handoff: Writer is a Lead tool

The Writer was first a stage that `run_turn` ran after the Lead. It is now the
Lead's `write_answer` tool (see "How a turn runs"). Files touched: `lead/tools.py`,
`lead/agent.py`, `lead/prompt.md`, `lead/schemas.py`, `writer/agent.py`,
`request_state.py` (`final_answer`, `writer_calls`), `run_turn.py`, plus the new
`write_answer.py` and `collected_evidence.py`. Tests in `test_run_turn.py` cover a
Lead that skips the tool, a bad alignment returned to the Lead, the per-request
Writer cap, and the budget-spent fallback. The live-model caveat above also
covers the new tool.

## Source behavior confirmed in Phase 3

- If a feed endpoint returns an HTML replacement page, discovery reports
  `extraction_failed`. A supported feed with no matches can return `no_results`.
- Washington Examiner remains in the approved roster. Reads below the existing
  100-word threshold return `incomplete_text`.
- Candidates pass the outlet's initial host check. Retrieval still checks
  redirects, canonical hosts, the publication date, and article completeness.

The offline suite passed 173 backend tests and 4 frontend tests. The frontend
production build passed.
