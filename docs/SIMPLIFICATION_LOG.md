# Gerry simplification log

This log compares the current implementation with commit `080cf05`, the Phase 4
baseline. It also describes intermediate changes where a later refactor replaced
an earlier one. The [codebase guide](CODEBASE_GUIDE.md) describes the current
runtime by subsystem.

## 1. Turn orchestration and shared agent runner

### The research brief owns the publication window

**Before.** `RequestState` stored both a `ResearchBrief` and a separate
`window` tuple. The first research call set both. Loading a saved brief on a
follow-up also had to rebuild the tuple.

**Now.** The dates live on the brief. `check_brief()` validates the proposed
brief, compares its event and dates with the saved brief, and returns the
validated date pair for the Researcher tools. The request state restores the
brief and findings when it loads a follow-up.

**Why.** The event and dates are one piece of trusted state. There is one place
to look when checking whether a follow-up can use a proposed window. A later
research call still gets a specific rejection if it changes either the event or
the dates. [Lead brief check](../src/backend/agents/lead/tools.py) ·
[Request state](../src/backend/application/turn/request_state.py)

### The turn handles limits where it decides what the reader gets

**Before.** `run_lead_stage()` returned the Lead outcome, a correction problem,
and a Boolean indicating whether it hit a limit. `run_turn()` discarded the
problem string and used the flag to choose a branch and later choose a failure
category.

**Now.** The Lead stage returns its validated outcome or `None`. A model-call
budget exception, SDK turn-limit exception, or deadline timeout reaches
`run_turn()`, which handles the limit directly. It records the failure, uses
an already-rendered answer if available, or tries to render a partial list of
headlines from accepted evidence. A limit with no usable evidence produces the
existing research-limit result. An exhausted correction attempt follows the
invalid-output path.

**Why.** The code no longer needs a special Boolean and an unused error field to
describe the same result. The limit handler sits with the code that chooses the
reader-facing fallback. [Turn workflow](../src/backend/application/turn/run_turn.py)

### Corrections share one append path and use typed input

**Before.** The shared runner used `Any` for SDK input, hook parameters, and
output. Its exception and validation branches each appended a correction
message to a separately assembled input list.

**Now.** The wrapper accepts the SDK's input item type, uses typed run context
and hook parameters, and carries a generic output type inferred from the
validator. The SDK's dynamically typed final output is cast at the point where
it has already been checked against the agent's configured schema. Each failure
branch still chooses its own correction wording and history. Both branches use
one place to append the correction message.

**Why.** The boundary between SDK data and application validation is explicit.
A schema or SDK behavior error still uses the input available before the failed
run. When Python rejects an otherwise structured output, the correction still
uses the SDK's returned history, including tool results. The runner still
allows one correction and charges every model call to the shared budget.
[Structured runner](../src/backend/application/turn/structured_run.py)

## 2. Lead tool wiring

### Tool builders read the request state from the active run

**Before.** The Lead's two research tool builders and its Writer tool builder
received the current `RequestState` as a construction argument and captured
it in their closures. The Lead runner also supplied that same state through
the SDK context.

**Now.** The registered functions receive `RunContextWrapper[RequestState]`
and read the state when the SDK invokes them. Their builders still bind the
model and model settings, and each research builder still binds its fixed
source group. The functions still use the SDK's `function_tool()` and start
nested agents through the shared runner.

**Why.** A tool gets the active request state through the same mechanism already
used by the Writer's saved-article tool. Before and after the change, the three
Lead tools had matching model-facing names, descriptions, and argument
schemas. [Lead tool registration](../src/backend/agents/lead/agent.py) ·
[Tool builders](../src/backend/agents/lead/tools.py)

### Research failures return at the point where they occur

**Before.** `research_group()` carried a nullable window, a nullable error,
and a nullable Researcher outcome through the budget checks, nested run, and
final failure condition. The final block needed to reconstruct whether the
run could proceed and which error to report.

**Now.** Invalid briefs, exhausted round allowances, budget exceptions,
turn-limit exceptions, and unsuccessful Researcher results return through one
local failure path. That path records the call and returns the same JSON failure
shape. The success path appends findings, saves the brief and findings for the
conversation, and records a successful tool call.

**Why.** The code that detects a failure also chooses its explanation.
The shared failure path avoids repeating tool-call logging and JSON formatting.
The Researcher still runs inside the request's concurrency limit.
[Group research wrapper](../src/backend/agents/lead/tools.py)

## 3. Researcher and evidence validation

### Accepted findings travel through the runner result

**Before.** The Researcher validation callback copied model output to replace
its group with the assigned group, checked the copy, and appended it to an
`accepted` list. The runner also returned the original output. The caller
checked that output for success, then retrieved the accepted copy from the
side list.

**Intermediate change.** The callback's side list was removed. The Researcher
used the runner result, although a copy was still made for validation and a
second copy was made for the returned result.

**Now.** `validate_findings()` takes `assigned_group` explicitly. It checks
article and passage IDs against saved conversation evidence using that trusted
group. The Researcher copies the accepted result once to set the group before
returning it to the Lead.

**Why.** The assignment and the model's group label are different inputs. The
validation function can use the trusted assignment directly, and the accepted
findings travel through a single return path. A model-supplied group label
cannot make another group's article eligible. The model-facing findings schema
still includes the group. [Researcher run](../src/backend/agents/researcher/agent.py) ·
[Findings validation](../src/backend/application/evidence/findings_validation.py)

### Search has one response builder for per-outlet failures

**Before.** An exhausted search budget and a rejected query each constructed
an `ArticleSearchResult` with one failure per assigned outlet. The
budget-exhaustion branch also logged and returned separately.

**Now.** Both branches call the same per-outlet response builder with their
own status and detail. All handled searches reach one logging call. The
unused `_group` field was removed from `GroupSourceTools`, since the class
already stores the derived outlet list and agent name. Article-read retry
eligibility is now a direct check for `FETCH_FAILED` instead of membership in a
one-element set.

**Why.** Each distinction that affects behavior is visible in the branch
that needs it. An exhausted search budget still skips the source call, a
rejected query still produces `FETCH_FAILED` for each outlet, and article-read
retries still consume a read budget unit per attempt.
[Researcher tools](../src/backend/agents/researcher/tools.py)

## 4. Source discovery and article-read results

### Discovery accumulates only what the outlet result needs

**Before.** Discovery collected all page candidates in a list and built a
dictionary afterward to deduplicate them by URL. It collected every page
failure in a second list even though the final outlet result used only the last
error and whether any page had failed. The combined feed and article host list
was assembled during each page fetch.

**Now.** Each outlet builds its allowed host tuple once, accumulates candidates
in a URL-keyed dictionary, and retains the last error. Dictionary insertion
order preserves the first appearance of a URL, while a later candidate for that
URL replaces its metadata. The existing per-outlet cap is applied after
deduplication.

**Why.** The accumulators now match the data the code returns. An outlet with
usable candidates still reports success and can mention a failed discovery
page. With no candidates, the last error still supplies the status and HTTP
detail if there was an error. Otherwise the outlet reports no results.
[Source search](../src/backend/sources/service.py)

### Article-read failures share one result construction

**Before.** Each exception branch built an `ArticleReadResult` and
`SourceAccessOutcome`, repeating the outlet, URL, and failure envelope.

**Now.** The branches choose or retain a `SourceAccessError` and one return
path builds the outcome from it. Fetch errors, extraction or validation
errors, and existing typed source errors still map to their respective
statuses and safe details.

**Why.** It is easier to inspect the status mapping when the response shape
appears once. The fetch, extraction, date validation, snapshot reuse, and
deduplication checks still run through the same source service.
[Article read](../src/backend/sources/service.py)

## 5. Writer workflow and citation rendering

### The Lead's table and the Writer's claims are checked separately

**Before.** The alignment validator rebuilt the allowed passage set for each
group in each row. The Writer report validator scanned the articles again,
then collected passage IDs from the claims and the already-checked alignment.
A Writer correction repeated that work.

**Now.** `write_answer()` indexes the eligible passage IDs once per source
group. The alignment is checked against those groups before invoking the
Writer. The union of the same sets is available to the Writer validator, which
checks only the Writer's claims and the answer mode on each attempt. The
helper that combined claim and alignment IDs was removed. Unknown claim IDs
still appear once in correction feedback, in their first-seen order.

**Why.** The Lead owns the table input and the Writer owns the claims. A
correction to the Writer's output has no effect on the already-validated
alignment. Building the indexes before invocation gives each check the
evidence it needs without walking the articles for every row or attempt.
[Writer workflow](../src/backend/application/answer/write_answer.py) ·
[Citation checks](../src/backend/application/answer/answer_rendering.py)

### The Writer's input is assembled before invocation

**Before.** `build_writer_input()` was nested inside the message dictionary
inside the runner call. `write_answer()` also accepted a `notes` argument that
no caller supplied.

**Now.** A named `writer_input` holds the same prompt content before the
runner is invoked. The unused `notes` parameter was removed from
`write_answer()`. The renderer still accepts notes directly from the
research-limit fallback.

**Why.** The evidence package and the SDK call can be read independently.
There is one entry point for limit notes, at the place where the partial answer
is rendered. The Writer's saved-article tool still exposes collected article
metadata and passages. [Writer workflow](../src/backend/application/answer/write_answer.py) ·
[Limit fallback](../src/backend/application/turn/run_turn.py)

### Citation numbers and excerpts share one ordered mapping

**Before.** `CitationNumbers` kept separate dictionaries for article numbers
and the first cited passage. It sorted the articles by number to build the
source list and used a list membership check to avoid repeated markers within
one claim.

**Now.** One insertion-ordered dictionary stores each article's number and
first cited passage together. Iterating it gives source order directly.
An ordered dictionary of marker numbers deduplicates each set of citations
while preserving its order.

**Why.** The citation number and its excerpt come from the same first citation.
Repeated references still use the same number, and the excerpt still comes
from the first cited passage. [Citation rendering](../src/backend/application/answer/answer_rendering.py)

## 6. Browser UI and local startup

### A single FastAPI server serves the page and API

**Before.** React and TypeScript rendered the UI. Local development used Vite
on port 5173 and a separate FastAPI process on port 8080. Vite proxied the API.
The frontend had an npm manifest, lockfile, TypeScript configuration, build
step, and dedicated Vitest suite.

**Intermediate change.** The React chat briefly consolidated its separate
active, progress, retry, and error values into one typed turn state. The
vanilla frontend replaced that implementation.

**Now.** FastAPI serves the HTML at `/` and the assets under `/static`. The
page uses plain HTML and CSS, one application JavaScript module, and a locally
bundled copy of Markdown-it 15.0.3 with its license notices. One process serves
the page and API at the same origin. The application runs without Node, npm,
Vite, or a frontend build step.

**Why.** The UI is small enough for native browser APIs. The browser uses
`fetch` for chat, `EventSource` for progress, and standard links and
`<details>` for citations. The Markdown library handles the briefing markup
and tables with raw HTML disabled. The browser still resends the original
payload on retry, renders follow-ups in order, and resets the visible state
when the reader starts a new chat. Browser verification focused on the briefing
format that Gerry generates. General-purpose Markdown extensions vary by renderer.
[Browser page](../src/frontend/index.html) ·
[Chat script](../src/frontend/static/chat.js) ·
[FastAPI routes](../src/backend/interfaces/http/app.py)

### Verification moved to the HTTP boundary and browser smoke checks

**Before.** Dedicated React tests covered the shell, chat, and answer rendering,
and the frontend build provided a separate TypeScript check.

**Now.** An HTTP test checks that FastAPI serves the chat page, JavaScript, and
CSS. The migration was also smoke-tested in Chrome with scripted replies,
including health recovery, SSE progress, a dropped response and exact retry,
a follow-up, comparison tables, adjacent citation links, source excerpts,
unsafe Markdown input, and new-chat reset. The dedicated frontend suite was
retired as agreed.

**Why.** The static application has no React components or compiler to test.
HTTP and browser checks exercise the new serving arrangement and user flow.
[HTTP tests](../tests/backend/interfaces/http/test_app.py) ·
[Local development instructions](../README.md)

During local verification, an older Gerry process was still answering on
loopback port 8080 and returning 404 for the new page and assets. Stopping it
allowed the updated process to serve them. This was a local process issue.
The working tree also contains a separate `litellm[google]` dependency and
lockfile update for the Google model integration.

## 7. Application layout and persistence

### Application modules are grouped by responsibility

**Before.** Turn handling, evidence selection, answer construction, tool-call
records, and SSE formatting were all in the root of `application/`.

**Now.** `application/turn/` contains orchestration, request state, budgets,
structured execution, failures, and tool-call recording. `application/evidence/`
contains outlet assignment lookups, findings validation, and selection of
collected articles. `application/answer/` contains the Writer workflow, sample
assessment, and rendering. Settings and composition stay at the application
root. Tool-call models and their recorder share `turn/tool_calls.py`. The
progress event and SSE encoder moved to the HTTP package, and its test moved
beside the other HTTP tests. Imports and the Phase 3 handoff paths were updated.

**Why.** A reader can find the module by following the workflow. Small pieces
that change together share a module. SSE encoding sits at the transport
boundary that uses it.
[Application layout](../src/backend/application/) ·
[Progress events](../src/backend/interfaces/http/progress_event.py)

### One private record owns each conversation

**Before.** The in-memory store kept separate dictionaries keyed by
`conversation_id` for the transcript, article snapshots, and saved research.
Claiming a turn scanned all request records to see whether any running request
belonged to that conversation.

**Now.** A private conversation record owns history, articles, optional
research, and the active request ID. Claiming a turn checks that conversation
directly. A separate request-ID dictionary still stores request records for
status checks and replay. Claim, completion, and interruption update the
active slot under the existing lock. Completion prepares the saved response
record before appending successful history. Failed HTTP responses can still
be replayed without adding to the transcript.

**Why.** One record initializes and holds everything scoped to a conversation.
The store can check whether that conversation is busy without inspecting other
requests. The lock still covers atomic request transitions and exact article
deduplication across concurrent saves. The store methods preserve scoped
article access and detached copies of conversation and research data.
[In-memory store](../src/backend/infrastructure/persistence/memory.py) ·
[Persistence tests](../tests/backend/infrastructure/test_memory_store.py)

## Verification and stopping point

The current backend suite has **179 passing tests**. Coverage includes
same-request replay, overlap rejection, follow-up history, reopening a
conversation after failure or interruption, concurrent article saves,
Researcher citation validation, Writer correction, and partial answers.

The final review deferred three optional follow-ups. They were representing the
remaining budget with one counter per resource, centralizing the flattened
findings view, and preparing the incoming article's duplicate-matching word
sequences once. [Request budget](../src/backend/application/turn/request_budget.py) ·
[Request state](../src/backend/application/turn/request_state.py) ·
[Article matching](../src/backend/sources/service.py)
