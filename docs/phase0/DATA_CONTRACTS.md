# Phase 0: proposed data boundaries

Latest implementation details are in [the Phase 2 handoff](../PHASE_2_HANDOFF.md).
The user's later in-memory storage decision supersedes the Firestore proposal
below; restart recovery is deferred for the prototype.

Person B contracts, November 8, 2026. Article/passages and source-result models
are implemented; discovery, retrieval, and persistence adapters remain future
work. Review cross-boundary changes with Person A before wiring the tools.

Public imports:

- `backend.sources.articles`: `ArticleRecord`, `ArticlePassage`, `PublicationDate`.
- `backend.sources.access`: `ArticleCandidate`, `SourceAccessOutcome`,
  `ArticleSearchResult`, `ArticleReadResult`.
- `backend.sources.constants`: `SOURCE_CONSTANTS` scopes article/access enums.

## Article and passage records

| Article field | Python type | Meaning |
| --- | --- | --- |
| `article_id` | `UUID` | Identifies one immutable saved snapshot. |
| `outlet_id` | `str` | Stable key from the approved outlet configuration. |
| `requested_url` | `str` | URL requested before validated redirects. |
| `canonical_url` | `str` | Validated publisher canonical URL; not an independent fetch permission. |
| `title` | `str` | Required nonempty article title. |
| `bylines` | `tuple[str, ...]` | Published author/agency credits for attribution; empty when unknown. |
| `published_at` | `datetime \| date \| None` | Publisher date, preserving available precision. |
| `updated_at` | `datetime \| date \| None` | Update date, distinct from publication. |
| `retrieved_at` | `datetime` | Aware UTC retrieval timestamp. |
| `article_type` | `ArticleType` | `reporting`, `analysis`, `opinion`, or `unknown`; keeps opinion/analysis separate from reporting. |
| `reporting_origin` | `str \| None` | Explicit original source, such as AP or Reuters; unknown stays null. |
| `syndicated` | `bool \| None` | True/false only when established; otherwise unknown. |
| `duplicate_of` | `UUID \| None` | Another saved snapshot identified as the same reporting. |
| `passages` | `tuple[ArticlePassage, ...]` | Ordered, nonempty article paragraphs after cleanup. |

| Passage field | Python type | Meaning |
| --- | --- | --- |
| `passage_id` | `str` | Snapshot UUID plus paragraph number, e.g. `<uuid>:p0001`. |
| `text` | `str` | Nonempty saved paragraph text. |

Full text is derived by joining passages with blank lines, avoiding a second copy.
Assign IDs once when saving; keep them unchanged when reading saved evidence.
Models are frozen, and passage IDs must match the snapshot UUID and sequential
paragraph number. Serialize UUIDs as strings when passing evidence IDs to Person
A's `MainFocus`; its existing string fields remain unchanged. A contract test
exercises this boundary. Reference resolution against saved evidence comes later.
Changed text creates a new snapshot, so old citations continue to resolve. Reuse
an existing saved snapshot for an unchanged canonical URL/content pair. Compare
saved text directly initially; a stored content hash is unnecessary at this scale.
Exact text equality does not detect near-duplicate syndicated reporting.

Keep extraction versions and date-selection diagnostics in run logs when needed,
rather than making them required article fields. Saved passages preserve the
actual evidence even when extraction code changes later.

Unknown metadata must not be fabricated. Aware datetimes retain their offsets;
a date-only publication stays a date, without invented midnight/timezone values.
The proposed search window is inclusive publisher calendar dates. Person A must
agree on that interpretation before connecting the brief. Conflicting or missing
publication dates exclude the article from a date-bounded comparison until resolved.
Extractor-wide date guesses are insufficient: the Fox sample demonstrates why.

## Source results

`search_articles` receives a query, inclusive start/end dates, and trusted outlet
assignments. A result contains candidates and per-outlet access outcomes.
`ArticleSearchResult` holds `candidates: tuple[ArticleCandidate, ...]` and
`outcomes: tuple[SourceAccessOutcome, ...]`. It requires at least one outcome,
one per queried outlet; every candidate must have a successful outlet outcome.
The caller remains responsible for checking against the trusted assignment.

| Candidate field | Python type |
| --- | --- |
| `outlet_id`, `url`, `title` | `str` |
| `snippet` | `str \| None` |
| `published_at` | `datetime \| date \| None` |

Candidates are discovery hints, never saved evidence or completed article reads.
Search dates are revalidated against publisher metadata during retrieval.

`read_article` receives a candidate URL plus trusted outlet/conversation context.
It returns either a validated, successfully saved article or an explicit failure.
`ArticleReadResult` holds `outcome: SourceAccessOutcome` and
`article: ArticleRecord | None`. Success requires an article from that outlet;
failure requires no article. These schemas cannot prove persistence occurred:
the future read implementation must finish saving before returning success.
`read_collected_article` receives an article ID plus conversation context and reads
only authorized saved evidence. It cannot fetch externally or silently refresh it.

Implemented access outcomes: `success`, `no_results`, `paywall`, `access_denied`,
`missing_date`, `date_conflict`, `outside_window`, `incomplete_text`, `fetch_failed`,
`extraction_failed`, `storage_failed`, and `budget_exhausted`. Outcomes carry
`outlet_id: str`, `url: str | None`, `http_status: int | None`, and
`detail: str | None`. Detail must be safe to expose. `no_results` describes the
search, never an assertion that an outlet published nothing. Mark a paywall only
when evidence supports it; a short body alone does not establish the cause.

Person A's wrappers bind source assignments and conversation identity outside
model-supplied arguments. Python checks hosts, redirects, dates, content limits,
and saved references. A successful read means extraction **and** persistence
succeeded. Partial search results retain successful candidates alongside failures.

## Outlet configuration

Keep one fixed record per outlet: `outlet_id: str`, `display_name: str`,
`group: SourceGroup`, `article_hosts: tuple[str, ...]`,
`feed_urls: tuple[str, ...]`, `feed_hosts: tuple[str, ...]`,
`classification: str`, `classification_url: str`,
`classification_scope: str`, and `classification_reviewed_on: date`.
Group is `liberal` or `conservative`, assigned by the project. The access report
contains the proposed roster and provenance. Keep exact host permissions rather
than authorizing every subdomain; explicitly account for ABC's observed redirect.
The roster/configuration model remains unimplemented. Reuse Person A's existing
`SourceGroup` rather than defining a competing group enum.

## Storage proposal and handoff

Start with two article operations: save a snapshot for a conversation and load an
authorized snapshot by ID. A failed or interrupted save must never expose a
partially saved article as complete. Do not add a generic repository hierarchy.

Firestore is a candidate for durable Cloud Run state, with its emulator for local
development. This is a recommendation, not a selected or provisioned backend.
Its [atomic operations](https://docs.cloud.google.com/firestore/native/docs/manage-data/transactions)
can support shared request state, but the final layout must respect the
[1 MiB document limit](https://docs.cloud.google.com/firestore/quotas).
Store articles separately from growing conversations. Agree on article size
limits before deciding whether passages need separate documents. No claim of
free production operation is made, and no cloud resource has been created.

Person A needs to review these concrete boundaries:

1. Date-window semantics, candidate/read results, statuses, and stable evidence IDs.
2. Application storage needs: messages, briefs, findings, completed responses,
   first-turn retry keys, atomic turn claims, and interrupted requests.
3. Ownership of retrieval/retry limits and how source calls consume the shared
   budget/deadline. Values remain open; no nested independent retry budgets.
4. Storage backend and credentials, retention, historical-search provider and
   spending ceiling. Route Python dependency changes through Person A.

API/history validation, progress transport, model selection, and request lifecycle
remain Person A's draft contracts. Do not invent them in source or UI code.

Person A's initial code was reviewed: `/chat` envelopes, brief, findings, tool
records, failure categories, and progress models/SSE encoding. No source code in
those components was changed. Access statuses are more granular than application
failures: Person A should map `storage_failed` to `PERSISTENCE_FAILURE` and
`budget_exhausted` to `RESEARCH_LIMIT_REACHED`, and agree how other source outcomes
produce a partial answer or request-level failure. `no_results` is not proof of
absent coverage or automatically an HTTP error.

The user confirmed public article/passage models, source-result models, and
compatibility with Person A's findings as this slice's test boundaries. Tests
followed red/green cycles and remain offline. Storage save/load tests belong to
the next agreed storage slice. Project dependency files were left unchanged.
