# Gerry: phased implementation plan

Updated: November 8, 2026.

This plan implements the agreed initial product recorded in the
[session summary](GRILLING_SESSION_SUMMARY.md). It is a plan, not a record of work
already completed. Source access, exact model, durable storage, research limits,
and progress transport still need decisions informed by early experiments.

## Implementation principles

1. Build a complete workflow for one specified event before recent-event discovery
   and the expanded-report experience.
2. Follow the OpenAI Agents SDK patterns in the supplied lectures. Keep clarification
   in the Lead; use identical Researcher prompts with different outlet assignments.
3. Give Python control over source restrictions, dates, persistence, citations,
   retries, and budgets. Prompts do not enforce hard limits.
4. Keep one repository, one application, and initially one Cloud Run service.
5. Keep primary source under `src/backend/` and `src/frontend/`. Use deep, cohesive
   components and small public interfaces; do not create speculative abstractions.
6. Apply the user's Python coding rules and TDD skill throughout application work.
   Develop one behavior at a time: test, observe failure, implement, refactor.
7. Keep ordinary tests deterministic and offline. Run paid model and external
   retrieval checks deliberately. Do not add merge-blocking CI.
8. Defer Langfuse and detailed eval work. Initial tool traces and diagnostic logs
   remain required.

## Phase 0 — Establish contracts and resolve source feasibility

### Work

- Review the ten candidate outlets in the session summary. Confirm the political
  assignments with the project owners and record the classification provenance.
- Test article discovery and full-text extraction for recent and historical events
  across the candidate outlets. Use several event types, not one convenient story.
- Distinguish missing coverage, missing search results, paywalls, automated-access
  restrictions, missing dates, extraction failure, and syndicated duplicates.
- Investigate public feeds, outlet search, and search-service options. Do not assume
  free recent discovery solves arbitrary date-range searches.
- Record what is possible without paid search, what is unreliable, and whether the
  required historical search experience needs a different service or scope.
- Select the initial model, research budgets, storage backend, and progress
  transport. Pin compatible SDK versions after checking actual interfaces.
- Specify contracts for articles, passages, outlet configuration, research briefs,
  findings, source-access results, progress events, and tool-call records.
- Specify the four-field `/chat` response and request/history validation. Define
  how request retries and interrupted turns behave.
- Check course uniqueness registration and the required `submission.json` format.
  Record missing inputs; do not fabricate compliance or write to the sign-up sheet
  without authorization.

### Completion criteria

- Both developers can implement against written, typed boundary contracts.
- A source-access matrix identifies tested capabilities and unresolved failures.
- At least two usable outlets per side have demonstrated discovery and extraction
  for the initial demonstration event; this is not a guarantee for all events.
- The proposed five-per-side roster is approved or explicitly revised based on
  access results. Do not disguise a reduced usable pool as ten working outlets.
- Cost, historical coverage, and persistence decisions are documented.

## Phase 1 — Create the modular application foundation

### Work

- Establish `src/backend/` and `src/frontend/`, initializing source directories with
  `__init__.py` as required. Keep frontend tooling compatible with those files.
- Create only the component packages needed for the first vertical slice:
  `application`, `agents`, `sources`, `interfaces/http`, and
  `infrastructure/persistence`.
- Use `agents/lead/`, `agents/researcher/`, and `agents/writer/` as they acquire code.
  Keep prompts beside the corresponding implementation in Markdown.
- Add explicit typed configuration for one shared model and research limits.
  Centralize shared systemic strings using the required Enum/dataclass pattern.
- Add dependency setup, environment documentation, an example environment file
  without secrets, and test commands.
- Set up the Python HTTP application and React/TypeScript development workflow.
  FastAPI is a candidate, not a previously settled requirement.
- Build a composition root that constructs concrete clients and storage adapters;
  components accept narrow dependencies rather than initializing global clients.
- Keep the existing root entry point thin or replace it through an agreed migration;
  application logic belongs under `src`.

### Completion criteria

- A fresh checkout can install dependencies and start the backend and frontend.
- A basic endpoint and frontend shell run without contacting a model provider.
- Configuration failures produce actionable startup messages without secret values.
- Shared configuration and package initialization follow the user's coding rules.

## Phase 2 — Implement source tools and durable article storage

### Work

- Implement fixed, typed outlet records and group assignments.
- Implement `search_articles` through the discovery approach selected in Phase 0.
- Implement `read_article`: fetch, extract, validate full text, persist an article
  snapshot, and return stable article and passage references.
- Record canonical URLs, bylines, dates, retrieval time, original reporting source,
  article type, and syndicated status when available.
- Deduplicate canonical URLs and recognize syndicated or substantially duplicated
  reporting. Preserve distinct publication choices without calling them independent
  reporting origins.
- Enforce approved hosts, source assignments, date bounds, response-size limits,
  timeouts, and bounded retries in code. Validate redirects as well as initial URLs.
- Treat article text as untrusted data, not agent instructions. Tools must not fetch
  arbitrary private-network addresses supplied by the model or a redirect.
- Implement `read_collected_article` against saved evidence only.
- Implement storage interfaces and selected adapters. Local development can use a
  simpler adapter, but Cloud Run state must not rely on instance-local memory/files.

### Completion criteria

- Representative articles produce useful clean text with valid passage references.
- Offline tests cover source restrictions, dates, redirects, duplicate handling,
  incomplete extraction, fetch failure, and storage round trips.
- Search results cannot be mistaken for completed article reads.
- Storage failure is explicit; a failed save is never reported as successful.

## Phase 3 — Build the specified-event agent workflow

### Work

- Implement the Lead's clarification behavior and structured research brief.
- Implement one Researcher factory and one shared prompt. Bind liberal and
  conservative source assignments through trusted runtime context and tools.
- Expose `research_liberal_coverage` and `research_conservative_coverage` as tools
  that run the same Researcher in fresh contexts.
- Ensure the Lead issues the initial research assignments in one turn and that
  both execute concurrently. Verify actual execution; a parallel setting alone
  does not demonstrate rubric compliance.
- Researchers read full text and return central focuses, supporting passage IDs,
  attributed accounts, source inventory, and gaps using validated schemas.
- Let the Lead align aspects and request targeted, fresh-context follow-ups without
  sharing the other group's conclusions in researcher prompts.
- Enforce both minimum sample coverage and hard research limits in Python.
  Distinguish agent turns from research rounds and total retrieval counts.
- Implement the Writer using findings and supporting passages, with access only to
  collected articles. Route missing evidence back to the Lead within the same
  request-wide budget.
- Validate article/passage references and allow one correction attempt. Never
  present invented references. Keep a readable citation representation in `answer`.
- Record sub-agent calls and their nested tool activity with agent identity.

### Completion criteria

- A clear event produces an attributed, cited comparison from both groups.
- Ambiguous input asks a useful clarification before launching broad research.
- Tests demonstrate initial concurrent execution and fresh-context isolation.
- Identical coverage can produce a finding of no clear difference; the system does
  not manufacture partisan contrast.
- Insufficient coverage and exhausted budgets yield qualified partial results or
  an explicit inability to compare.
- The Writer does not independently browse or decide to ignore collection limits.

## Phase 4 — Deliver `/chat`, session persistence, and the briefing UI

### Work

- Connect `POST /chat` to the same application workflow used outside HTTP.
- Accept message history, a nullable conversation ID, and a per-turn request ID.
  Restrict accepted message roles and validate history against backend state.
- Generate a conversation ID on the first turn and persist messages, research briefs,
  articles, findings, and completed request results.
- Make repeated request IDs idempotent within a conversation. Define first-turn
  retry handling before the client has received a conversation ID, and reject
  reuse of a request ID with a different payload.
- Prevent concurrent turns from corrupting one conversation. Surface in-progress
  or interrupted requests instead of silently duplicating expensive research.
- Return only `conversation_id`, `request_id`, `answer`, and `tool_calls` at the top
  level. Include citations and meaningful gaps in the answer itself.
- Implement the chosen progress transport while preserving the final contract.
  Any additional endpoint is supporting infrastructure; `/chat` remains the main
  interaction endpoint.
- Build the frontend purpose statement, input, clarification exchange, progress
  display, complete briefing, aspect comparison table, source links, and expandable
  supporting evidence.
- Keep active session identity in browser memory. Refresh starts a new conversation;
  do not restore old research or add a history interface.
- Support follow-up questions using saved research and a stable event/time window.

### Completion criteria

- The first complete vertical slice works through the browser.
- Refresh starts a new conversation. An active session can reuse its saved
  research until the backend process restarts, per the prototype storage decision.
- Network retries do not create duplicate completed turns or duplicate research.
- Every visible progress message corresponds to real work. Puns are restrained;
  error messages remain straightforward.
- The table is usable on small screens and citations are navigable.

## Phase 5 — Complete error handling and operational resilience

Error handling begins in Phases 1–4. This phase exercises failures across the whole
application and closes gaps; it is not permission to postpone error handling.

### Work

- Define typed failure categories and map them to tool records, HTTP statuses,
  progress events, and plain-language answers.
- Exercise search/fetch failures, partial extraction, missing dates, rate limits,
  model failures, invalid output, invalid citations, researcher failure, storage
  errors, budget exhaustion, and unexpected exceptions.
- Retry only eligible transient failures with bounded backoff, respecting a shared
  deadline and budget. Do not stack retries into an unbounded total.
- Preserve successful research when another branch fails. Never silently let the
  Lead invent findings for the missing branch.
- Handle browser disconnects and interrupted requests using the selected request
  lifecycle. Do not leave unsupported background tasks running after returning a
  response; durable background execution would require an explicit design.
- Log request/conversation IDs, agent identity, tool outcomes, timing, retry counts,
  and available usage metadata. Keep credentials and stack traces out of answers.
- Return the agreed four-field envelope for handled failures. The frontend also
  handles malformed responses, network failure, or process death with no envelope.

### Completion criteria

- Failure-injection tests exercise each major boundary and recovery path.
- Partial answers visibly identify meaningful missing coverage.
- Users can understand what failed and whether retrying is appropriate.
- Tool records include failed calls and sub-agent activity, not just successful tools.

## Phase 6 — Add recent-event discovery and detailed reports

### Work

- Implement `search_recent_events` over approved sources.
- Offer five suitable international events from the prior seven days, with dates,
  short descriptions, and a visible selection rule. Explain smaller result sets.
- Reuse the discovery machinery for event disambiguation within a supplied period.
- Let the user select an event and enter the existing specified-event workflow.
- Separate "view evidence" from "investigate further" in the frontend.
- Add detailed-report requests and angle-specific follow-up research. Reuse saved
  evidence first, then request new research where the existing record is inadequate.
- Maintain attribution, date discipline, source restrictions, and request-wide
  limits throughout expanded reports.

### Completion criteria

- Both original entry paths work end to end.
- A detailed report adds supported depth, while the briefing remains complete.
- The system can explain that no suitable recent events or no additional evidence
  were found without manufacturing material.

## Phase 7 — Build and validate the Cloud Run deployment

### Work

- Package the HTML, CSS, and JavaScript assets with the FastAPI application in
  one deployable image.
- Configure the service's port, startup/health behavior, runtime configuration,
  secrets, external storage permissions, timeouts, and bounded concurrency.
- Confirm that persisted state is available across instances and deployments.
- Ensure progress delivery works through the deployed transport and that long
  requests fail or terminate cleanly within configured limits.
- Test source discovery and extraction from the deployed environment; local access
  does not guarantee access from a cloud address.
- Check that deployment resources and model/search credentials are ready before
  publishing. Do not commit secrets.

### Completion criteria

- The frontend and `/chat` are reachable at the deployed service URL.
- Run one successful event comparison, one clarification, one follow-up, and one
  controlled failure against the deployed service.
- Validate refresh behavior, request retries, storage durability, and citations.
- Record known coverage/access limits without claiming universal outlet support.

## Phase 8 — Revisit rigorous evals and finalize the submission

This phase is intentionally after the initial implementation, following the user's
scope decision. Unit/integration tests remain part of every earlier phase.

### Work

- Review `evaluations.pdf` with the working workflow in hand and agree on eval
  scope, framework, budget, reference-labeling process, and scoring criteria.
- Consider Inspect AI and the lecture's Agents SDK bridge so evals exercise the
  actual workflow rather than a second implementation.
- Design reproducible saved-evidence cases separately from live retrieval checks.
  Evaluate clarification, retrieval, focus identification, faithful synthesis,
  citation support, overlap, and honest partial responses.
- If adopting the full Evals path requirements voluntarily, explicitly commit to
  at least 50 documented samples, at least two scorer kinds, a baseline, and two
  improvement rounds. Keep examples out of prompt few-shots and report uncertainty.
  These are not already mandatory under the chosen Deep Research path.
- Use development cases for iteration and a held-out set for final assessment;
  account for multiple questions sharing one event when interpreting uncertainty.
- Write the README: purpose, users, data sources/loading, architecture, setup,
  deployed URL, three sample queries with expected answers and evidence locations,
  and same-model no-tools/no-system-prompt comparisons.
- Create `submission.json` using the course-specified schema and verify uniqueness
  registration. Include required research traces and known limitations.

### Completion criteria

- The README and submission metadata match the actual deployed behavior.
- Deep Research rubric requirements have concrete demonstrations.
- Eval claims, if included, are reproducible and accurately describe what was run.
- No invented results, traces, model baselines, or source-access claims appear.

## Two-person implementation split

The objective is clear file ownership and stable interfaces, not isolated work that
only meets at the end. Both developers first agree on boundary contracts, then
build against controlled substitutes until the other side is ready.

### Primary ownership

| Area | Person A: agent workflow and API | Person B: data access, storage, and UI |
| --- | --- | --- |
| `src/backend/agents/` | Owns agent definitions, prompts, schemas, and tool wrappers | Reviews source-tool integration |
| `src/backend/application/` | Owns orchestration, sessions, budgets, retries, and composition | Supplies persistence and data-access dependencies |
| `src/backend/interfaces/http/` | Owns `/chat`, progress transport, validation, and error mapping | Consumes API contracts from the frontend |
| `src/backend/sources/` | Consumes public interfaces | Owns roster, discovery, retrieval, extraction, article records, and passages |
| `src/backend/infrastructure/persistence/` | Defines application storage requirements in coordination | Owns concrete adapters and storage implementation |
| `src/frontend/` | Reviews workflow behavior | Owns browser assets, tables, evidence expansion, progress, and errors |
| Tests | Owns tests for agents/application/API | Owns tests for sources/storage and browser smoke checks |
| Deployment configuration | Owns backend/image/Cloud Run wiring | Reviews deployed UI |

This split gives each component one primary editor. It is not a rule that Person B
must complete all source and UI work simultaneously. Schedule the work below to
avoid blocking.

### Work sequence and handoffs

| Stage | Person A | Person B | Handoff |
| --- | --- | --- | --- |
| Phase 0 | Drafts API, brief, findings, progress, and error contracts | Runs source-access experiments; drafts article/passage and storage contracts | Joint review; one designated editor applies each contract change |
| Phase 1 | Creates backend foundation and agent interfaces | Creates source/storage skeletons and frontend shell | Both can run independently with fixtures |
| Phase 2 | Builds Lead/Researcher/Writer behavior against source substitutes | Implements real discovery, extraction, and persistence | Stable source results and article IDs replace substitutes |
| Phase 3 | Integrates real tools and proves concurrent fresh-context research | Tests source edge cases; begins frontend table and evidence UI | One end-to-end backend comparison |
| Phase 4 | Completes `/chat`, idempotency, progress publication, sessions | Connects frontend and tests persistence with application flows | Browser vertical slice |
| Phase 5 | Tests model/agent/API failures | Tests retrieval/storage/browser failures | Joint failure walkthrough |
| Phase 6 | Adds discovery orchestration and deeper-research flow | Adds recent-event discovery support and corresponding UI | Both product journeys complete |
| Phase 7 | Owns deployment integration and runtime configuration | Validates cloud source access, frontend behavior, and storage | Deployed smoke test |
| Phase 8 | Focuses on agent/synthesis evals and architecture documentation | Focuses on retrieval/data cases and usage/data documentation | Joint scoring and final submission review |

### Shared files that need one editor

- **Person A:** root Python dependency manifest/lockfile, backend bootstrap,
  deployment files, final `submission.json`, and README integration.
- **Person B:** frontend dependency manifest/lockfile, frontend configuration, outlet
  roster, source-access matrix, and data-loading instructions.
- **Contract modules:** owner follows the component. Article and passage contracts
  belong to Person B; workflow and API contracts belong to Person A. Review
  cross-boundary changes together before changing either consumer.
- **README:** Person B supplies data/setup sections as a patch or separate draft;
  Person A integrates them to avoid simultaneous root-file edits.

### Practices that reduce conflicts

1. Use short-lived branches with the `codex/` prefix by default and small changes
   grouped by component or behavior.
2. Agree on contract changes before implementation. Avoid renaming shared fields
   independently on both branches.
3. Keep test fixtures local to the owning component unless genuinely shared. Give
   shared fixtures one owner.
4. Do not run repository-wide formatting or reorganize another person's component
   in an unrelated change.
5. Route Python dependency changes through Person A and frontend dependency changes
   through Person B so lockfiles have one editor.
6. Integrate at each handoff, not only after both halves are complete. Test the real
   boundary as soon as implementations exist.
7. Coordinate directly on conflicts and substantive reviews; no merge-blocking CI
   or additional approval bureaucracy is required.
