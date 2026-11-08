# Phase 2: Person B source layer

The composition root exposes `app.state.sources`, an `ArticleSourceService`
using the same `InMemoryStore` as `app.state.store`. There is no model dependency
or paid search API in this component.

Public synchronous operations:

- `search_articles(query, start_date, end_date, assigned_outlets)` returns
  discovery candidates and per-outlet outcomes, without collecting evidence.
- `read_article(url, outlet_id, conversation_id, start_date, end_date,
  assigned_outlets)` extracts and saves a validated snapshot or returns a failure.
- `read_collected_article(conversation_id, article_id)` reads saved evidence only.

Agent wrappers should use `asyncio.to_thread` for search/read operations, bind
assignments and conversation identity from trusted context, and enforce the
application's shared call budget, concurrency cap, and request deadline.
The source layer bounds each HTTP operation's bytes, socket time, redirects,
and retries. Its defaults are 2 MB, 10 seconds, three redirects, and one retry.
Disable its retry when the application retries the same operation itself.
DNS lookup uses the platform resolver; its blocking duration remains controlled
by the OS rather than the socket timeout.

Discovery uses current RSS/Atom entries. Older windows use bounded NBC monthly
archives, CBS monthly sitemaps, and New York Post daily archives. Other outlets
return an explicitly qualified feed-only result. Historical completeness is
unknown, and archive pages/results are capped. Article reads independently check
publication dates. A search miss never establishes missing outlet coverage.

Only exact assigned HTTPS hosts are permitted. Redirects are checked before
connection, all resolved addresses must be public, and TLS connects to a checked
IP while verifying the publisher hostname. Article canonical URLs are restricted
to the same outlet's approved hosts.

Extraction uses `trafilatura==2.3.1` plus primary article JSON-LD/head metadata.
It preserves explicit bylines, date precision, content type, and wire attribution
where available. Conflicting/missing dates, explicitly gated content, non-HTML,
and text below 100 words are excluded. Length is a conservative screening rule,
not proof that a longer extraction is complete. Broader live extraction quality
and Cloud Run access remain unverified.

Collected URLs are reused within a conversation. Matching/near-matching reporting
is linked through `duplicate_of`, preserving distinct outlet records. Similarity
is a five-word-shingle Jaccard threshold of 0.85, not an independent-origin claim.
Exact-text duplicate handling also runs under the store lock, so simultaneous
collection does not lose that relation. Near-match detection uses the source
call's collected snapshot and remains best effort during concurrent writes.
Changed snapshots keep separate IDs. Store failure never returns a successful read.

Storage remains process-local by user decision. Restart recovery, live source
validation, full historical discovery, and the agent workflow are outside this
implemented slice. `/chat` remains the existing placeholder until Person A wires
the workflow. No paid model or search checks were run.
