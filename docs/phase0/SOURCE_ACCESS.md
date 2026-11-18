# Phase 0: source-access experiments

Tested November 8, 2026. Person B's first feasibility pass; Phase 0 is still open.
Measurements and tested article URLs are in
[source-access-results.json](source-access-results.json).

## Method and limits

- Direct local `curl` GETs, redirects enabled, 20-second timeout, 3 MB response
  limit. No authentication, browser automation, paid search calls, or model calls.
- Parsed RSS with Python's standard XML parser. Extracted article text with
  temporary `trafilatura==2.3.1`, without changing project dependencies.
- Used `bare_extraction` with `include_comments=False`, `include_tables=False`,
  `favor_precision=True`, and `with_metadata=True`. Word counts use `text.split()`.
- Recent URLs came from the feeds below. Historical URLs came from this chat's
  search tool; that is **not** an application discovery implementation.
- Checked titles, text boundaries, dates, bylines, and selected HTML paragraphs.
  Word counts describe extraction output, not proof of complete or clean text.
  Bodies remain temporary; the repository records metadata and response hashes.
- These are small local samples, not reliability measurements or Cloud Run tests.
  No missing-coverage conclusions follow from a failed search or read.

## Initial access matrix

Every feed below returned HTTP 200 and parseable RSS. Every sampled article GET
returned HTTP 200. Recent samples span a Polish shooting, Ukraine diplomacy/war,
and an Egyptian train collision. Historical samples concern Pope Francis's death
on April 21, 2025. A dash means not tested, not missing coverage.

| Outlet | Feed items | Recent extracted words | Historical extracted words | Qualification |
| --- | ---: | ---: | ---: | --- |
| NPR | 10 | 820 | — | Extracted text repeats heading; historical path remains open. |
| NBC | 25 | 1,378 | — | Feed mixes articles and videos; exclude video-only results. |
| HuffPost | 6 | 911 | — | Recent sample identifies Reuters reporting. |
| ABC | 25 | 620 | 2,116 | Recent sample is AP; feed redirects to `abcnews.com`. |
| CBS | 30 | 655 | 735 | Recent byline missing from extractor; feed includes transcripts/video. |
| Fox | 25 | 816 | 2,021 | Historical extractor date is wrong; publisher metadata says April 21. |
| Daily Caller | 25 | 580 | 4,755 | Historical text includes extensive embedded quotations; inspect cleanup. |
| Breitbart | 48 | 489 | 288 | Recent sample is AP; historical extraction includes an author bio. |
| New York Post | 20 | 613 | — | One recent sample; historical path remains open. |
| Washington Examiner | 10 | 85 | 71 | Only two body paragraphs in each response; completeness unresolved. |

None of these samples demonstrated a paywall or missing publication metadata.
This does not establish that either problem is absent elsewhere. The Examiner's
short responses cannot yet be classified as a paywall or complete articles.

For a first recent-event demonstration, the November 7–8 Polish shooting has
candidate text from NBC and HuffPost, and Fox, Daily Caller, and New York Post.
This provides two outlets per side for further validation. Do not count the
Examiner samples or claim all ten outlets are production-ready. Preserve wire
origins and distinguish changing publication times when comparing accounts.

## Tested feed endpoints

| Outlet | Requested feed | Observed redirect destination, if different |
| --- | --- | --- |
| NPR | <https://feeds.npr.org/1004/rss.xml> | — |
| NBC | <https://feeds.nbcnews.com/nbcnews/public/world> | — |
| HuffPost | <https://www.huffpost.com/section/world-news/feed> | <https://chaski.huffpost.com/us/auto/vertical/world-news> |
| ABC | <https://abcnews.go.com/abcnews/internationalheadlines> | <https://abcnews.com/abcnews/internationalheadlines> |
| CBS | <https://www.cbsnews.com/latest/rss/world> | — |
| Fox | <https://moxie.foxnews.com/google-publisher/world.xml> | — |
| Daily Caller | <https://dailycaller.com/feed/> | — |
| Breitbart | <https://www.breitbart.com/feed/> | <https://feeds.feedburner.com/breitbart> |
| New York Post | <https://nypost.com/world-news/feed/> | — |
| Washington Examiner | <https://www.washingtonexaminer.com/feed/> | — |

Feed hosts and article hosts are separate allowlists. A feed redirect does not
authorize article retrieval from that host. The CBS world feed returned mixed
content, so feed routing alone cannot enforce international reporting scope.

## Historical discovery and cost

Tested a WordPress-style search/feed URL on Daily Caller, Breitbart, and New York
Post using `s=pope%20francis&feed=rss&year=2025&monthnum=4&day=21` at each root.
Daily Caller returned 403; New York Post returned 410; Breitbart returned HTML,
not RSS. None demonstrated a working date-constrained feed search. Those results
describe the tested endpoints, not every search facility those outlets offer.

Free RSS is viable for initial recent discovery, but the sampled feeds do not
establish complete seven-day coverage or arbitrary historical search. Store
observed date ranges rather than assuming a feed contains every relevant article.

Two historical-search candidates have documented date filters:

- [Brave Web Search](https://api-dashboard.search.brave.com/app/documentation/web-search/query):
  custom `freshness` ranges such as `2025-04-21to2025-04-22`.
- [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search):
  `start_date`, `end_date`, and domain restrictions.

Neither API was exercised. Do not select a provider or promise historical recall
from documentation alone. Next compare them on the same events and all ten
outlets, with a credential and an agreed call/spend ceiling. Recheck current
pricing before that experiment. No paid search API or model API was invoked in
this pass; production cost remains unmeasured.

## Roster provenance

AllSides profiles were reviewed through the chat web tool on November 8, 2026.
Direct `curl` requests to all ten profiles returned 403. Classification lookup
is a project configuration task, not a runtime dependency. The classifications
below apply to online news, not an outlet's broadcast or separately rated opinion
content. These are attributed ratings; project-owner approval remains pending.

| Proposed group | Outlet/profile | AllSides rating |
| --- | --- | --- |
| Liberal | [NPR online news](https://www.allsides.com/news-source/npr-media-bias) | Lean Left |
| Liberal | [NBC Digital](https://www.allsides.com/news-source/nbc-news-media-bias) | Lean Left |
| Liberal | [HuffPost](https://www.allsides.com/news-source/huffpost-media-bias) | Left |
| Liberal | [ABC online](https://www.allsides.com/news-source/abc-news-media-bias) | Lean Left |
| Liberal | [CBS online](https://www.allsides.com/news-source/cbs-news-online-media-bias) | Lean Left |
| Conservative | [Fox Digital](https://www.allsides.com/news-source/fox-news-media-bias) | Right |
| Conservative | [Daily Caller](https://www.allsides.com/news-source/daily-caller-media-bias) | Lean Right |
| Conservative | [Breitbart](https://www.allsides.com/news-source/breitbart-news-media-bias) | Right |
| Conservative | [New York Post news](https://www.allsides.com/news-source/new-york-post-news-media-bias) | Right |
| Conservative | [Washington Examiner](https://www.allsides.com/news-source/washington-examiner-media-bias) | Lean Right |

## November 18, 2026 roster expansion

The roster grew from ten to fifteen outlets (eight liberal, seven conservative)
and most outlets gained a second feed. These checks were narrower than the
November 8 pass: `curl` GETs with the application's `Gerry/0.1` user agent,
one sampled article per outlet, and a search for `isAccessibleForFree`,
`headline`, and `datePublished` in the page. Article text was not extracted and
no historical samples were taken. Paywalled outlets were excluded by project
decision. AllSides ratings were looked up through the chat web search tool
because direct `curl` requests to AllSides returned 403.

### Added outlets

| Group | Outlet/profile | AllSides rating (confidence) | Feeds |
| --- | --- | --- | --- |
| Liberal | [The Guardian](https://www.allsides.com/news-source/guardian-media-bias) | Left (low; moved from Lean Left in Nov 2024) | `/us-news/rss`, `/us-news/us-politics/rss` |
| Liberal | [Salon](https://www.allsides.com/news-source/salon-media-bias) | Left (medium) | `/feed/`, `/category/politics/feed/` |
| Liberal | [Mother Jones](https://www.allsides.com/news-source/mother-jones-media-bias) | Left (low) | `/feed/`, `/politics/feed/` |
| Conservative | [Washington Free Beacon](https://www.allsides.com/news-source/washington-free-beacon-media-bias) | Right (high) | `/feed/` |
| Conservative | [Just the News](https://www.allsides.com/news-source/just-news-media-bias) | Lean Right (low) | `/rss.xml` |

Sampled feeds returned HTTP 200 with parseable RSS and 10 to 32 items. Salon's
feeds redirect within `www.salon.com`. The Just the News feed is not strictly
recent-first (an item from 2017 appeared near the top). The Guardian feed
contains live blogs. The Mother Jones sample article had no `headline` in its
structured metadata, so extraction from Mother Jones is untested. The Free
Beacon and Just the News samples declared no `isAccessibleForFree` value; that
does not establish that they are free everywhere.

### Added politics feeds for existing outlets

NPR (`feeds.npr.org/1014/rss.xml`), NBC (`/nbcnews/public/politics`), HuffPost
(`/section/politics/feed`), ABC (`/abcnews/politicsheadlines`), CBS
(`/latest/rss/politics`), Fox (`/google-publisher/politics.xml`), New York Post
(`/politics/feed/`), and Washington Examiner (`/category/news/politics/feed/`)
returned HTTP 200 with parseable RSS and were added next to each existing feed.
Daily Caller's politics feed returned 404 and Breitbart's politics feed
redirected to the same main feed, so both keep their single existing feed.

### Candidates tested and not added

| Outlet | Reason |
| --- | --- |
| Reason | AllSides rating is Center (moved from Lean Right in Sept 2024); roster accepts only Left, Lean Left, Lean Right, Right. |
| Vox, National Review, Newsweek | Sampled articles declared `isAccessibleForFree: false`. |
| Politico, Axios, The Hill, The Daily Signal | Article requests returned 403. |
| USA Today, Washington Times, The Federalist | Feed requests returned 402 or 403. |
| Daily Wire | Known membership paywall; not tested further. |
| Newsmax, Townhall, The Epoch Times, The Independent, Spectator, CBN | No usable feed found with the URLs tried. |
| Hot Air | AllSides page shows a 2.0 score but "Not Rated"; rating unclear. |
| The Blaze, RedState, PJ Media | Passed feed and article checks (Right) but are mostly opinion; not chosen. |

These results describe the specific URLs and user agent tried on this date.

### Archive discovery removed

NBC monthly archives, CBS monthly sitemaps, and New York Post daily archives
were removed from the application on November 18, 2026. The product asks users
to ask about recent news, so discovery uses only each outlet's current feeds.
The historical-search notes above record the original Phase 0 findings.

## Remaining source checks

- Validate historical discovery across all outlets and more event windows.
- Resolve short Examiner bodies, extraction cleanup, CBS bylines, and date conflicts.
- Run article extraction and date checks on the five added outlets, especially
  Mother Jones, and confirm the Just the News feed's date ordering.
- Compare syndicated text across outlets; attribution alone is not deduplication.
- Exercise missing dates, access restrictions, and fetch/extraction failures with
  controlled fixtures during implementation.
- Repeat representative reads from Cloud Run before claiming deployed access.
- Approve or revise the roster jointly; no replacements are silently introduced.
