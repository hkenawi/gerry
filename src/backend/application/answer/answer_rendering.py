"""
Render the reader-facing Markdown answer and verify its citations.

The Writer supplies claims tied to passage IDs; this module resolves each ID to
a saved article, numbers the citations, builds
the two-sided bullet lists. Invalid citations are
reported as problems so they can be corrected and are never shown to readers."""

import re

from uuid import UUID
from urllib.parse import quote

from backend.sources.articles import ArticleRecord
from backend.agents.topics.schemas import MAX_TOPICS, TOPIC_RESOLUTION, IssueResolution
from backend.application.evidence.topic_clusters import TopicOption
from backend.application.evidence.recent_events import TOPIC_QUESTION
from backend.sources.access import SourceAccessOutcome
from backend.agents.researcher_findings import SourceGroup
from backend.agents.writer.schemas import Claim, PassageQuote, WriterReport
from backend.sources.constants import ArticleType, SourceAccessStatus
from backend.application.evidence.outlet_assignments import group_for_outlet, outlet_display_name
from backend.application.answer.sample_assessment import AnswerMode, SampleAssessment
from backend.agents.lead.schemas import AspectAlignment, AspectTreatment, CoverageState

MAX_TOPICS_SHOWN: int = MAX_TOPICS
FEATURED_ASPECT_LIMIT: int = 3
FEED_SCOPE_NOTICE: str = "Gerry only searches current publisher feeds, so I skipped the date filter."
FAILURE_PHRASES: dict[SourceAccessStatus, str] = {
    SourceAccessStatus.NO_RESULTS: "the search found nothing usable",
    SourceAccessStatus.PAYWALL: "it appears to be behind a paywall",
    SourceAccessStatus.ACCESS_DENIED: "access was not permitted",
    SourceAccessStatus.MISSING_DATE: "its publication date could not be confirmed",
    SourceAccessStatus.DATE_CONFLICT: "its publication dates conflicted",
    SourceAccessStatus.OUTSIDE_WINDOW: "it was published outside the event window",
    SourceAccessStatus.INCOMPLETE_TEXT: "its full text could not be read",
    SourceAccessStatus.FETCH_FAILED: "it could not be fetched",
    SourceAccessStatus.EXTRACTION_FAILED: "its text could not be extracted",
    SourceAccessStatus.STORAGE_FAILED: "it could not be saved",
    SourceAccessStatus.BUDGET_EXHAUSTED: "the research limit was reached first",
    SourceAccessStatus.SUCCESS: "it succeeded",
}


def article_id_of(passage_id: str) -> str:
    """
    Return the article ID that prefixes a passage ID.
    """
    return passage_id.split(":", 1)[0]


def escape_excerpt(text: str) -> str:
    """Render source text as literal Markdown prose."""
    return re.sub(r"([\\`*_{}\[\]<>()#+.!|])", r"\\\1", text)


class CitationNumbers:
    """
    Assign citation numbers to articles in order of first appearance.
    """

    def __init__(self, articles: tuple[ArticleRecord, ...]) -> None:
        """
        Index the saved articles by ID and start with no numbers assigned.
        """
        self._articles: dict[str, ArticleRecord] = {
            str(article.article_id): article for article in articles
        }
        self._citations: dict[str, tuple[int, str]] = {}
        self._quotes_by_article: dict[str, dict[str, None]] = {}

    def cite(self, passage_ids: list[str]) -> str:
        """Return the numbered markers for the passages, assigning new numbers."""
        markers: dict[int, None] = {}
        passage_id: str
        number: int
        for passage_id in passage_ids:
            article_id: str = article_id_of(passage_id)
            number, _ = self._citations.setdefault(
                article_id, (len(self._citations) + 1, passage_id),
            )
            markers[number] = None
        return " " + "".join(f"[{number}]" for number in markers) if markers else ""

    def sources(self) -> list[ArticleRecord]:
        """Return cited articles ordered by their citation number."""
        return [self._articles[article_id] for article_id in self._citations]

    def outlet_names(self, passage_ids: list[str]) -> str:
        """Name the outlets whose passages support one aspect treatment."""
        return ", ".join(dict.fromkeys(
            outlet_display_name(self._articles[article_id_of(passage_id)].outlet_id)
            for passage_id in passage_ids
            if article_id_of(passage_id) in self._articles
        ))

    def record_quotes(self, quotes: list[PassageQuote]) -> None:
        """Attach verified quotes to their source entries in order of use."""
        for excerpt in quotes:
            article_id: str = article_id_of(excerpt.passage_id)
            text: str = " ".join(excerpt.text.split())
            self._quotes_by_article.setdefault(article_id, {})[text] = None

    def excerpts(self, article: ArticleRecord) -> tuple[str, ...]:
        """Return selected quotes or a short excerpt from the first cited passage."""
        article_id: str = str(article.article_id)
        selected: dict[str, None] = self._quotes_by_article.get(article_id, {})
        if selected:
            return tuple(escape_excerpt(text) for text in selected)
        passage_id: str = self._citations[article_id][1]
        for passage in article.passages:
            if passage.passage_id == passage_id:
                words: list[str] = passage.text.split()
                text: str = " ".join(words[:24]) + ("…" if len(words) > 24 else "")
                return (escape_excerpt(text),) if text else ()
        return ()


def find_report_problems(
    report: WriterReport,
    known_passage_ids: set[str],
    assessment: SampleAssessment,
    detailed: bool = False,
    *,
    passage_texts: dict[str, str] | None = None,
) -> list[str]:
    """Check the Writer's claims against the evidence, answer mode, and report type."""
    claims: list[Claim] = [
        *report.summary, *report.overlap, *report.differences,
        *report.discrepancies, *report.timeline,
    ]
    cited_passage_ids: dict[str, None] = dict.fromkeys(
        passage_id for claim in claims for passage_id in claim.passage_ids
    )
    problems: list[str] = [
        f"Passage ID {passage_id!r} does not exist in the collected articles."
        for passage_id in cited_passage_ids
        if passage_id not in known_passage_ids
    ]
    if passage_texts is not None:
        for claim in claims:
            for quote in claim.quotes:
                text: str = " ".join(quote.text.split())
                passage: str = passage_texts.get(quote.passage_id, "")
                if (
                    not text
                    or quote.passage_id not in claim.passage_ids
                    or text not in passage
                ):
                    problems.append(
                        f"Quote from {quote.passage_id!r} must be copied verbatim "
                        "from one of the claim's cited passages."
                    )
    if assessment.mode is not AnswerMode.COMPARISON and (
        report.overlap or report.differences or report.discrepancies
    ):
        problems.append(
            "Do not describe overlap, differences, or discrepancies: one side has "
            "no articles, so only an objective summary is allowed."
        )
    if not detailed and (report.discrepancies or report.timeline):
        problems.append(
            "For a briefing or direct follow-up, leave discrepancies and timeline empty."
        )
    return problems


def find_alignment_problems(
    alignment: list[AspectAlignment],
    passage_ids_by_group: dict[SourceGroup, set[str]],
    *,
    main_focus_passages: dict[SourceGroup, set[str]] | None = None,
) -> list[str]:
    """Check which groups and article-level findings support each treatment."""
    problems: list[str] = []
    for row in alignment:
        for group, treatment in (
            (SourceGroup.LIBERAL, row.liberal),
            (SourceGroup.CONSERVATIVE, row.conservative),
        ):
            allowed: set[str] = passage_ids_by_group[group]
            problems.extend(
                f"Aspect {row.aspect!r} cites passage {passage_id!r}, which is "
                f"not from a {group.value} article you were given."
                for passage_id in (*treatment.passage_ids, *treatment.incidental_passage_ids)
                if passage_id not in allowed
            )
            if (
                main_focus_passages is not None
                and treatment.state is CoverageState.CENTRAL
                and not set(treatment.passage_ids) <= main_focus_passages[group]
            ):
                problems.append(
                    f"For {row.aspect!r}, cite only recorded main-focus passages in the "
                    f"{group.value} central treatment. Put passing mentions separately."
                )
    return problems


def describe_treatment(
    treatment: AspectTreatment,
    numbers: CitationNumbers,
    sample_available: bool,
) -> str:
    """Describe what actual sampled outlets made central or mentioned."""
    if not sample_available:
        return "No usable articles for this sample."
    if treatment.state is CoverageState.NOT_IN_SAMPLE:
        return "Not found in the sampled articles."
    outlets: str = numbers.outlet_names(treatment.passage_ids)
    label: str = (
        "Main focus at" if treatment.state is CoverageState.CENTRAL else "Mentioned by"
    )
    text: str = f"{label} {outlets}{numbers.cite(treatment.passage_ids)}."
    if treatment.note:
        text += " " + " ".join(treatment.note.split())
    incidental: list[str] = treatment.incidental_passage_ids
    if incidental:
        text += (
            f" Also mentioned by {numbers.outlet_names(incidental)}"
            f"{numbers.cite(incidental)}."
        )
    return text


def render_aspect_cards(
    alignment: list[AspectAlignment],
    numbers: CitationNumbers,
    represented: set[SourceGroup | None],
) -> str:
    """Show the leading aspects first and retain additional aspects under their own heading."""
    cards: list[str] = []
    for row in alignment:
        if CoverageState.CENTRAL not in (row.liberal.state, row.conservative.state):
            continue
        aspect: str = escape_excerpt(" ".join(row.aspect.split()))
        liberal: str = describe_treatment(row.liberal, numbers, SourceGroup.LIBERAL in represented)
        conservative: str = describe_treatment(
            row.conservative, numbers, SourceGroup.CONSERVATIVE in represented,
        )
        cards.append(
            f"### {aspect}\n\n**Liberal coverage:** {liberal}"
            f"\n\n**Conservative coverage:** {conservative}",
        )
    if not cards:
        return ""
    sections: list[str] = ["## Coverage aspects", *cards[:FEATURED_ASPECT_LIMIT]]
    if len(cards) > FEATURED_ASPECT_LIMIT:
        sections.extend(("## More aspects", *cards[FEATURED_ASPECT_LIMIT:]))
    return "\n\n".join(sections)


def render_cited_claim(claim: Claim, numbers: CitationNumbers) -> str:
    """Render a cited claim and set aside its quotations for the source list."""
    numbers.record_quotes(claim.quotes)
    return " ".join(claim.text.split()) + numbers.cite(claim.passage_ids)


def render_claims(claims: list[Claim], numbers: CitationNumbers) -> str:
    """
    Render claims as bullets with numbered citations.
    """
    return "\n".join(f"- {render_cited_claim(claim, numbers)}" for claim in claims)


def render_failed_reads(failed_reads: list[SourceAccessOutcome]) -> list[str]:
    """
    Describe each failed article in plain language.
    """
    return [
        f"- We could not use an article from {outlet_display_name(outcome.outlet_id)}: "
        f"{FAILURE_PHRASES[outcome.status]}."
        for outcome in failed_reads
    ]


def render_sources_section(citations: CitationNumbers) -> str:
    """
    Render the Sources section with numbered links and excerpts.
    """
    lines: list[str] = ["## Sources"]
    for number, article in enumerate(citations.sources(), start=1):
        line: str = (
            f"{number}. {outlet_display_name(article.outlet_id)}: "
            f"[{article.title}]({article.canonical_url})"
        )
        if article.published_at is not None:
            line += f", {article.published_at.isoformat()}"
        if article.article_type is not ArticleType.REPORTING:
            line += f" ({article.article_type.value})"
        lines.append(line)
        for excerpt in citations.excerpts(article):
            lines.append(f"\n{' ' * (len(str(number)) + 2)}> {excerpt}")
    return "\n".join(lines)


def normalize_claim_text(text: str) -> str:
    """Compare whole words regardless of casing, punctuation, or whitespace."""
    return " " + re.sub(r"\W+", " ", text.casefold()).strip() + " "


def merge_repeated_claims(claims: list[Claim]) -> list[Claim]:
    """Keep the first wording of each claim and retain all its cited evidence."""
    by_text: dict[str, Claim] = {}
    for claim in claims:
        key: str = normalize_claim_text(claim.text)
        previous: Claim | None = by_text.get(key)
        by_text[key] = claim if previous is None else previous.model_copy(update={
            "passage_ids": list(dict.fromkeys([*previous.passage_ids, *claim.passage_ids])),
            "quotes": [*previous.quotes, *claim.quotes],
        })
    return list(by_text.values())


def render_claim_paragraph(claims: list[Claim], numbers: CitationNumbers) -> str:
    """Render one paragraph of distinct paraphrased claims with citations."""
    return " ".join(render_cited_claim(claim, numbers) for claim in merge_repeated_claims(claims))


def render_followup(
    report: WriterReport,
    articles: tuple[ArticleRecord, ...],
) -> str:
    """Answer the reader's follow-up directly and include only its cited sources."""
    citations: CitationNumbers = CitationNumbers(articles)
    sections: list[str] = [render_claim_paragraph(report.summary, citations)]
    if citations.sources():
        sections.append(render_sources_section(citations))
    return "\n\n".join(sections)


def render_answer(
    report: WriterReport,
    alignment: list[AspectAlignment],
    assessment: SampleAssessment,
    articles: tuple[ArticleRecord, ...],
    failed_reads: list[SourceAccessOutcome],
    notes: tuple[str, ...] = (),
    *,
    detailed: bool = False,
) -> str:
    """
    Render a short briefing or a detailed report, every claim cited by number.
    """
    numbers: CitationNumbers = CitationNumbers(articles)
    comparing: bool = assessment.mode is AnswerMode.COMPARISON
    sections: list[str] = []
    summary: str = render_claim_paragraph(report.summary, numbers)
    if detailed:
        if not comparing:
            sections.append(f"> {assessment.reason}")
        sections.append("## What the coverage reports\n" + summary)
    else:
        sentences: list[str] = [summary]
        if assessment.reason:
            sentences.append(assessment.reason)
        sentences.extend(notes)
        sections.append(" ".join(sentences))
    if comparing:
        shown: set[str] = {normalize_claim_text(claim.text) for claim in report.summary}
        for heading, coverage in (
            ("Where coverage overlaps", report.overlap),
            ("Where coverage differs", report.differences),
        ):
            fresh: list[Claim] = [
                claim for claim in coverage if normalize_claim_text(claim.text) not in shown
            ]
            if fresh:
                sections.append(f"## {heading}\n" + render_claim_paragraph(fresh, numbers))
                shown.update(normalize_claim_text(claim.text) for claim in fresh)
    represented: set[SourceGroup | None] = {
        group_for_outlet(article.outlet_id) for article in articles
    }
    cards: str = render_aspect_cards(alignment, numbers, represented)
    if cards:
        sections.append(cards)
    if assessment.mode is AnswerMode.SUMMARY_ONLY:
        sections.append("Choose another issue from the front page for a two-sided comparison.")
    if detailed:
        for heading, claims in (
            ("Reporting discrepancies", report.discrepancies),
            ("Timeline", report.timeline),
        ):
            if claims:
                sections.append(f"## {heading}\n" + render_claims(claims, numbers))
        if notes:
            sections.append(" ".join(notes))
    if assessment.show_footnote:
        sections.append(f"*Sample: {assessment.sample_statement}.*")
    if numbers.sources():
        sections.append(render_sources_section(numbers))
    return "\n\n".join(sections)


def render_no_evidence_answer(
    reason: str,
    failed_reads: list[SourceAccessOutcome],
) -> str:
    """
    Render the answer used when no article could be read from either side.
    """
    lines: list[str] = ["## No coverage could be retrieved", reason]
    failures: list[str] = render_failed_reads(failed_reads)
    if failures:
        lines.append("\n".join(failures))
    return "\n\n".join(lines)


def render_topic_options(
    found: tuple[TopicOption, ...],
    most_covered: tuple[TopicOption, ...],
    query: str,
    date_filter_requested: bool,
    *,
    resolution: IssueResolution = TOPIC_RESOLUTION.resolutions.NARROW,
    issue_ids: tuple[UUID | None, ...] = (),
) -> str:
    """Render current-feed results and explain why a requested date filter was ignored."""
    shown: tuple[TopicOption, ...] = (found or most_covered)[:MAX_TOPICS_SHOWN]
    subject: str = f" for “{query}”" if query else ""
    lines: list[str] = []
    if date_filter_requested:
        lines.extend((FEED_SCOPE_NOTICE, ""))
    if not found:
        lines.append(f"No comparison topics found{subject} in the current feeds.")
        if not shown:
            return "\n".join(lines)
        lines.extend((
            "",
            "Take a look at the most-covered topics from the current feeds "
            "and choose one you’re interested in:",
        ))
    elif resolution is TOPIC_RESOLUTION.resolutions.BROADEN:
        lines.append("This headline is part of a broader issue. Which issue would you like compared?")
    else:
        lines.append("Which of these topics would you like compared?")
    lines.append("")
    for number, option in enumerate(shown, start=1):
        question_text: str = TOPIC_QUESTION.format(topic=option.label)
        issue_id: UUID | None = issue_ids[number - 1] if number <= len(issue_ids) else None
        selection: str = f"&issue={issue_id}" if issue_id is not None else ""
        lines.append(
            f"{number}. [{option.label}](#compare-event={quote(question_text, safe='')}"
            f"&headline={quote(option.label, safe='')}{selection})"
        )
    return "\n".join(lines)
