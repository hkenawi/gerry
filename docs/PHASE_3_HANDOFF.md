# Phase 3: Person A agent workflow

Date: November 8, 2026. Written for Person B. Everything here is offline-tested
against a scripted model and fake sources. **No real Gemini or source call has been
made by this code.** Nothing here is wired into `/chat` yet; that is Phase 4.

## What exists

Public entry point: `backend.application.run_turn.run_turn(messages, state, model,
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
| `write_answer` (mode, validation, Writer run, rendering, storage) | `application/write_answer.py` |
| Shared evidence view (articles per group) | `application/collected_evidence.py` |
| Source tool wrappers (group, window, budget, retries) | `agents/researcher/tools.py` |
| Shared budget | `application/request_budget.py` |
| Run with one correction attempt | `application/structured_run.py` |
| Sample counts and answer mode | `application/sample_assessment.py` |
| Findings checked against saved evidence | `application/findings_validation.py` |
| Markdown rendering and citation checks | `application/answer_rendering.py` |
| Orchestration | `application/run_turn.py` |

Prompts are Markdown beside each agent (`prompt.md`).

## How a turn runs

1. **Lead** (one run). An unclear event or period ends with a clarifying question
   and no research. A clear one calls `research_liberal_coverage` and
   `research_conservative_coverage` in the same turn; the SDK runs them
   concurrently. Each wraps a fresh-context Researcher. The first call fixes the
   date window for the request; later calls must reuse it.
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
   fix. `write_answer` allows at most 2 Writer attempts per request
   (`MAX_WRITER_CALLS`).
5. **Lead finishes** with a brief only. `LeadOutcome` no longer carries the
   alignment. The Lead's validation rejects a clear brief unless research ran and
   `write_answer` succeeded (one correction attempt, as before).
6. **Fallback.** If the Lead hits a budget, turn, or time limit after research,
   `run_turn` runs `write_answer` directly with an empty alignment and a limit
   note, uncapped. If nothing was retrieved it returns the research-limit failure.

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
- **Writer runs are not counted against the model-call budget**, so finished
  research is not discarded; each is bounded by `max_turns` (4) and one correction,
  and `write_answer` by 2 attempts per request. The Lead's own calls, including
  the ones that call `write_answer`, are counted.
- **Time:** the Lead stage (research and the Writer tool) gets the full
  `request_deadline_seconds`. The fallback Writer then gets 30% of it, so a request
  can overrun the deadline by up to that share. The old 70/30 split no longer
  applies. A timeout during research proceeds with what was found.
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
Writer cap, and the budget-spent fallback. 168 tests pass offline. The live-model
caveat above also covers the new tool.

## Questions for you

1. `search_articles` for a group returns one outcome per outlet. I treat
   `no_results` and `success` as a successful tool record. Is `no_results` ever
   raised for an outlet that was reachable but returned an unusable feed?
2. Washington Examiner reads under 100 words become `incomplete_text`. Expect that
   outlet to appear in the failed-article lines often; should the roster change?
3. The real `search_articles` may return candidate URLs on hosts the read tool then
   rejects. Please confirm candidates are always readable by `read_article`.
