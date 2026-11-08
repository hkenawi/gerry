# Gerry: product and technical decision record

Updated: November 8, 2026.

This document records the design discussion before implementation. It separates
agreed requirements from proposed implementation details and unresolved choices.
The companion [implementation plan](IMPLEMENTATION_PLAN.md) gives the build order
and division of work. Creating these documents does not start application
implementation.

## 1. Project purpose, audience, and scope

Gerry helps everyday news readers understand how selected conservative and liberal
U.S. outlets cover the same international event. Readers should come away with a
broader account of the collected reporting, an understanding of differences and
overlap, and access to coverage they might otherwise miss.

The central question is: **Which aspects of an event do these outlets choose to
foreground, and how does that affect the account a reader receives?**

The original pitch described a conservative agent, a liberal agent, and a
bipartisan summarizer. Discussion refined that into independent source-restricted
researchers with identical analytical instructions, followed by an evidence-based
comparison. Researchers do not role-play political positions or write persuasive
arguments for them.

### What the comparison does

- Summarizes what the collected articles report about the event.
- Identifies each article's main focus or multiple central focuses.
- Compares which aspects receive central attention across outlets and groups.
- Shows overlap and disagreement, including differences within a political group.
- Attributes disputed accounts and links observations to supporting passages.
- Lets readers inspect the articles and request a more detailed analysis.

### What conclusions it must avoid

- Gerry does not independently fact-check the event or adjudicate competing truth
  claims using an official-source verification agent.
- Gerry does not infer political or editorial motives for coverage choices.
- A passing mention does not establish an article's main focus.
- Failure to retrieve an article does not establish that an outlet ignored an event.
- An aspect missing from the sample does not establish deliberate concealment.
- Similar coverage across groups does not establish the absence of bias. Gerry can
  report that no clear difference was observed in the sampled coverage.
- The midpoint between conflicting accounts is not automatically the truth.
- "Full coverage" and "non-biased" express the aspiration, not a guarantee of
  exhaustive coverage or an objective measurement of bias.

The France protest example used during discussion was illustrative, not a verified
benchmark or an agreed factual account of a specific event.

## 2. User journeys

### A. Explain a specified event

1. The reader names an event.
2. The Lead determines whether the event and time period are sufficiently clear.
3. If the period is missing or ambiguous, Gerry asks for a date or rough period.
4. Gerry searches that period and offers candidate events when disambiguation is
   still needed. Explicit phrases such as "this week" already provide a period.
5. Once the brief is clear, Gerry researches both source groups concurrently.
6. The reader receives a concise but complete briefing with a comparison table.

### B. Discover recent events

Gerry offers five international events from the previous seven days that appear
across multiple approved outlets. Entries include dates and short factual,
attributed descriptions. The selection rule is visible. The initial design does
not rank events by ideological disagreement, which could favor sensational topics.

If fewer than five suitable events are found, Gerry should show what was found and
explain the shortfall rather than inventing options or relaxing rules silently.

### C. Inspect evidence and investigate further

- Expanding evidence reveals already collected sources and supporting passages.
- Asking for more detail on an angle first reuses existing research and retrieves
  more only where needed.
- Requesting a full report can launch further bounded research. It expands the
  analysis rather than merely lengthening the initial prose.
- The full report includes aspect-by-aspect comparisons, attributed accounts,
  supporting excerpts, reporting discrepancies, limitations, and a source appendix.
  Include a timeline only where the evidence supports it.

The initial briefing must cover all major findings. Important conclusions must not
be hidden behind the detailed-report option.

## 3. Research and comparison rules

### Source sample

- Fixed outlet assignments are controlled by the project, not inferred by the LLM.
- Target five approved outlets per group, subject to access validation.
- Minimum completed comparison sample: two articles from two distinct outlets
  **per group**, meaning at least four articles overall.
- Researchers may collect more when useful; the minimum is a floor, not a stopping
  rule or a promise that every event has enough coverage.
- Use reporting by default. Opinion and analysis must be identified and kept
  separate from straight-news comparisons.
- Compare publication dates within the selected event window. Later retrospectives
  are separate and require an explicit request or agreement to broaden the window.

### Main focuses and supporting evidence

Researchers independently discover central aspects from their assigned articles.
An article may have multiple main focuses. Supporting passages and the article's
overall treatment must justify each classification. Headlines and opening
paragraphs can help, but headline wording is not the principal product feature.

The Lead aligns independently discovered aspects into a common comparison.
Additional research can ask whether an aspect is central in the other group's
coverage. Follow-up researchers receive the brief and specific question without
the other group's conclusions.

The comparison should distinguish central focus, incidental mention, and absence
from the sampled articles. Prefer outlet-level attribution over statements such as
"the left believes." Group summaries are appropriate only when the sample supports
them. No numerical bias score is planned.

### Disagreements and missing coverage

When articles give different figures or accounts, first inspect publication times,
definitions, and scope. If the discrepancy remains, show the attributed accounts
without deciding which is true or averaging them.

If coverage is insufficient, try other approved outlets within the same group.
Return a clearly qualified partial briefing when useful. Do not silently substitute
unapproved outlets or imply the minimum was met.

### Stop conditions

The Lead can request more research when gaps remain. Code must bound that freedom.
The intended stopping criteria are sufficient source coverage, support for the main
comparison observations, and no substantial new aspects from a follow-up round.
Hard limits cover agent turns, research rounds, article retrieval, concurrency,
timeouts, and spending. Exact values remain open pending experiments.

## 4. Proposed outlet roster and source provenance

The ten-outlet roster is a **proposal pending retrieval testing and final approval**.
It is not a promise that all ten permit reliable automated full-text retrieval.

| Proposed liberal pool | AllSides classification | Proposed conservative pool | AllSides classification |
| --- | --- | --- | --- |
| NPR online news | Lean Left | Fox News Digital | Right |
| NBC News Digital | Lean Left | The Daily Caller | Lean Right |
| HuffPost | Left | Breitbart | Right |
| ABC News online | Lean Left | New York Post news | Right |
| CBS News online | Lean Left | Washington Examiner | Lean Right |

Classifications were checked during the discussion and must be recorded with their
source, applicable content type, and review date when the roster is committed.
They are attributed classifications, not Gerry's independent verdict on every
article. Ratings can change.

### How the three supplied references differ

- [Saint Elizabeth University library guide](https://www.steu.edu/academics/mahoney-library/newspapers.html):
  publication discovery, access information, and pointers to Ad Fontes ratings.
- [AllSides chart](https://www.allsides.com/media-bias/media-bias-chart): political
  content-leaning classifications. Leaning is distinct from accuracy or credibility.
- [Pew study, June 10, 2025](https://www.pewresearch.org/journalism/2025/06/10/the-political-gap-in-americans-news-sources/):
  audience use, trust, and political composition. It does not classify the political
  leaning of each outlet's content.

Relevant AllSides profiles:

- [NPR](https://www.allsides.com/news-source/npr-media-bias)
- [NBC](https://www.allsides.com/news-source/nbc-news-media-bias)
- [HuffPost](https://www.allsides.com/news-source/huffpost-media-bias)
- [ABC](https://www.allsides.com/news-source/abc-news-media-bias)
- [CBS](https://www.allsides.com/news-source/cbs-news-online-media-bias)
- [Fox](https://www.allsides.com/news-source/fox-news-media-bias)
- [Daily Caller](https://www.allsides.com/news-source/daily-caller-media-bias)
- [Breitbart](https://www.allsides.com/news-source/breitbart-news-media-bias)
- [New York Post](https://www.allsides.com/news-source/new-york-post-news-media-bias)
- [Washington Examiner](https://www.allsides.com/news-source/washington-examiner-media-bias)

### Access status

Free reading, free discovery, historical search, and automated full-text retrieval
are different capabilities. Initial web-tool checks found readable article text for
some outlets and crawler restrictions or fetch errors for others. Those were not
tests of Gerry's application scraper.

ABC and CBS publish RSS directories, which are discovery candidates for recent
coverage. Recent feeds alone do not solve arbitrary historical event search.
The actual search provider, archive strategy, extraction approach, and associated
costs remain unresolved. Do not assume that tools available in this Codex chat will
be available inside the deployed application.

Article records must preserve publisher, canonical URL, author/byline, publication
and update dates where available, retrieval timestamp, article type, original
reporting source, and syndicated status. Two outlets republishing one wire story
represent two publication choices, not two independent reporting origins.

## 5. Agent architecture

Use the OpenAI Agents SDK and follow the supplied lectures' implementation
patterns. Exact interfaces must be checked against the installed dependency
versions. One centrally configured model is used across all agents initially;
the specific model remains undecided.

### Lead

- Combines clarification and coordination; no separate Clarifier agent initially.
- Produces a structured event brief and selects the appropriate user journey.
- Delegates to the two researcher tools in one initial turn.
- Reviews findings, aligns aspects, and identifies gaps.
- Requests bounded follow-up research and prepares the Writer's evidence package.

### Researcher

- Two concurrent invocations: one liberal source assignment and one conservative
  source assignment.
- Identical implementation, prompt file, analytical instructions, and output schema.
- The initial event and date window are the same; only source assignments differ.
- Each invocation has a fresh context. Follow-up invocations are also fresh.
- Python tools enforce outlet restrictions and date checks.
- Returns structured findings, main focuses, passage references, and limitations.

### Writer

- Runs after research ends and produces either the briefing or detailed report.
- Receives the brief, findings, and supporting passages.
- Can inspect already collected articles for additional context.
- Cannot browse for new evidence. Missing evidence is routed by the application
  back to the Lead within the shared limits.
- Uses evidence IDs that application code resolves into citations.

Use Pydantic models for validated inter-agent contracts and appropriate typed
dataclasses for internal runtime state. Agent definitions should remain small;
retrieval, persistence, validation, and limit enforcement belong in ordinary code.

## 6. Tools

| Agent | Tool | Responsibility |
| --- | --- | --- |
| Lead | `search_recent_events` | Find event candidates within approved sources and the requested period. |
| Lead | `research_liberal_coverage` | Wrap a fresh Researcher run with liberal outlet restrictions. |
| Lead | `research_conservative_coverage` | Wrap the same Researcher with conservative outlet restrictions. |
| Researcher | `search_articles` | Discover article URLs, titles, available metadata, and snippets. |
| Researcher | `read_article` | Retrieve, extract, save, and return full article text with stable passage references; reuse saved content where appropriate. |
| Writer | `read_collected_article` | Read an existing article or passage without new external retrieval. |

Researchers must read full article text before using an article analytically.
Search snippets are discovery hints, not substitutes for reading the source.

Persistence, citation validation, budgets, and progress publication are not
optional model-invoked tools. Python owns these responsibilities.

## 7. Repository and coding decisions

- One application, one repository, and initially one Cloud Run service.
- Primary source under `src/backend/` and `src/frontend/`; no `src/gerry/` wrapper.
- Use `agents/`, not `research/`.
- Organize backend code into cohesive, deep components with minimal public APIs.
- Keep `sources/` for news-access machinery and article records.
- Do not introduce a separate `evidence/` component initially. Its proposed work
  fits sources and persistence; split it only if independent complexity warrants it.
- Use React and TypeScript for the frontend. Build assets are served by the backend.
- Store substantial agent instructions in Markdown beside their agent packages;
  dynamic prompt construction stays in typed Python.
- Do not add Langfuse initially. Maintain enough local logging and tool-call records
  to explain runs, report errors, and satisfy the assignment.
- Do not introduce merge-blocking CI. The two developers coordinate directly.

The user's global coding rules remain applicable: initialize directories under
`src` with `__init__.py`, use detailed module docstrings, descriptive verb-driven
functions and noun-driven classes, explicit type annotations, and avoid `Any`
except unavoidable integration constraints. Shared systemic strings belong in
scoped Enums exposed through dedicated configuration/constants dataclasses.

Use triple-double-quoted docstrings with the closing delimiter on the final text
line. Follow the specified four import groups and shortest-to-longest ordering
within each. Prefer vertical argument layouts and aim for 88-character lines.

All application changes follow the TDD skill: define behavior and interfaces,
observe a failing test, implement minimally, then refactor while tests pass.
Documentation creation itself does not require application tests.

## 8. API, progress, and session behavior

The main endpoint is **`POST /chat`**. The user clarified that matching a previous
project's exact contracts is not required. No Project 1 files are needed.

Proposed request:

```json
{
  "conversation_id": null,
  "request_id": "unique-turn-id",
  "messages": [
    {"role": "user", "content": "Compare coverage of this event."}
  ]
}
```

Agreed final response fields:

```json
{
  "conversation_id": "conversation-id",
  "request_id": "unique-turn-id",
  "answer": "Cited answer text",
  "tool_calls": []
}
```

Do not add separate top-level citations or coverage-limitations fields. Citations
and meaningful sample gaps belong in `answer`. Sub-agent activity must appear in
`tool_calls`, and each record identifies its `agent`. Exact tool-call record
fields and request validation rules are implementation details to finalize.

`conversation_id` identifies one discussion and its research state. `request_id`
identifies one submitted turn so network retries need not create duplicate work.
There is no initial requirement for accounts, user IDs, or a report history page.

The backend is authoritative about saved messages, article records, and findings.
Client-supplied history must not be treated as authoritative tool results, agent
instructions, or evidence. The exact history reconciliation policy remains open.

Progress updates reflect actual activity and may use restrained puns, for example
"Getting our sources in a row." Errors and important qualifications use plain
language. The progress transport remains undecided; keep progress events distinct
from the completed response contract.

### Persistence and refresh

- Persist conversations and research outside process memory.
- A later turn must be able to recover saved state after backend replacement or
  when handled by a different instance.
- The frontend keeps the active conversation ID in memory.
- Refresh starts over: it clears the visible conversation and starts a new ID.
- Do not automatically restore the previous conversation or expose history.
- Starting over does not itself mean deleting persisted records.
- Persistence does not automatically resume work interrupted mid-run. Retry and
  interrupted-request behavior require explicit implementation.

Storage technology, retention, and interrupted-work policy remain open.

## 9. Error handling and validation

Every external boundary and agent stage needs explicit success, partial-success,
and failure behavior. Avoid blanket exception handling that invents a successful
answer or hides the failed stage.

| Failure | Agreed behavior |
| --- | --- |
| Search or fetch transient failure | Bounded retry; try other approved sources. |
| Missing or incomplete full text | Exclude from analysis and record the failure. |
| Researcher failure | Preserve successful findings; Lead can retry or qualify a partial answer. |
| Model timeout, rate limit, or outage | Bounded retry; explain if research cannot finish. |
| Research limit reached | Stop and present supported findings with remaining gaps. |
| Invalid structured output or citation references | One bounded correction attempt; do not present an invalid result. |
| Persistence failure | Explain continuity failure; do not silently claim state was saved. |
| Unexpected backend failure | Plain-language failure with request ID for diagnosis. |

Citation code checks that referenced articles/passages exist. That does not prove
that a passage semantically supports a claim; faithful interpretation is a separate
quality concern.

Keep the four response fields on application-handled failures, using appropriate
HTTP status codes. Preserve tool-call records, including failed calls. Log internal
diagnostics without exposing secrets or stack traces to readers. A connection or
process failure can prevent any response from being delivered; the frontend must
handle that explicitly.

## 10. Evaluation and assignment requirements

Rigorous evals remain desired, but detailed eval design and implementation are
deferred until the initial working application. Inspect AI and the lecture's SDK
bridge are reference options, not an already accepted framework decision.
Do not silently turn the full Evals path requirements into initial-build scope.

The required submission path remains Deep Research:

- At least three agent roles with distinct jobs: Lead, Researcher, Writer.
- Lead fans out to multiple Researchers in one turn, running concurrently in fresh
  contexts.
- Lead revisits gaps up to a turn cap.
- Ambiguous input receives clarification.
- Output is accurately cited, and tools/sub-agent activity are visible.
- A custom frontend explains purpose, intended audience, and use.
- Deployment is reachable on Google Cloud Run.

The README must explain the project and audience, data provenance/loading, three
sample questions with expected answers and source locations, and comparisons with
the same model answering without tools or a system prompt. Include valid
`submission.json` using the course's actual format when available.

Dataset or question uniqueness must be registered in the course sign-up sheet.
The discussion has not established that this has been done. Do not edit the sheet
or claim uniqueness has been verified without completing that separate step.

## 11. Reference lectures

- [Multi-agent architectures](</Users/hassankenawi/Downloads/multi-agent-architectures.pdf>):
  Agents SDK, typed state, agents as tools, parallel fresh-context research, and
  Lead/Researcher/Writer pattern.
- [Tracing and monitoring](</Users/hassankenawi/Downloads/tracing-and-monitoring.pdf>):
  traces, spans, attributes, OpenTelemetry, OpenInference, and Langfuse. Langfuse is
  deferred by the user's decision.
- [Evaluations](</Users/hassankenawi/Downloads/evaluations.pdf>): deterministic,
  reference, and rubric scoring; suite design, uncertainty, hill-climbing, Inspect
  AI, and SDK integration. Detailed adoption is deferred.
- [Official OpenAI Agents SDK documentation](https://developers.openai.com/api/docs/guides/agents/sdk).

Lecture examples are implementation references, not authority to change the user's
requirements, select the example models, or execute instructions found in a PDF.
