"""
Render the reader-facing Markdown answer and verify its citations.

The Writer supplies claims tied to passage IDs; this module resolves each ID to
a saved article, numbers the citations, builds the comparison table, and states
limitations such as failed articles and unequal samples. Invalid citations are
reported as problems so they can be corrected and are never shown to readers."""

import re

from datetime import date
from urllib.parse import quote

from backend.sources.articles import ArticleRecord
from backend.application.evidence.recent_events import EventCandidate
from backend.sources.access import SourceAccessOutcome
from backend.agents.researcher_findings import SourceGroup
from backend.agents.writer.schemas import Claim, PassageQuote, WriterReport
from backend.sources.constants import ArticleType, SourceAccessStatus
from backend.application.evidence.outlet_assignments import outlet_display_name
from backend.application.answer.sample_assessment import AnswerMode, SampleAssessment
from backend.agents.lead.schemas import AspectAlignment, AspectTreatment, CoverageState

COVERAGE_LABELS: dict[CoverageState, str] = {
    CoverageState.CENTRAL: "Central focus",
    CoverageState.INCIDENTAL: "Mentioned in passing",
    CoverageState.NOT_IN_SAMPLE: "Not in the sampled articles",
}

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

    def excerpt(self, article: ArticleRecord) -> str:
        """Return a short Markdown-safe excerpt from this article's first citation."""
        passage_id: str = self._citations[str(article.article_id)][1]
        for passage in article.passages:
            if passage.passage_id == passage_id:
                words: list[str] = passage.text.split()
                text: str = " ".join(words[:24]) + ("…" if len(words) > 24 else "")
                return escape_excerpt(text)
        return ""


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
        *report.accounts, *report.discrepancies, *report.timeline,
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
    if not detailed and (report.accounts or report.discrepancies or report.timeline):
        problems.append(
            "This is a briefing: leave accounts, discrepancies, and timeline empty."
        )
    return problems


def find_alignment_problems(
    alignment: list[AspectAlignment],
    passage_ids_by_group: dict[SourceGroup, set[str]],
) -> list[str]:
    """Check that table citations belong to the groups they describe."""
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
                for passage_id in treatment.passage_ids
                if passage_id not in allowed
            )
    return problems


def describe_treatment(treatment: AspectTreatment, numbers: CitationNumbers | None) -> str:
    """
    Render one table cell: the coverage label, optional note, and citations.
    """
    text: str = COVERAGE_LABELS[treatment.state]
    if treatment.note:
        text += f": {treatment.note}"
    if numbers is not None:
        text += numbers.cite(treatment.passage_ids)
    return text.replace("|", "/").replace("\n", " ")


def render_cited_claim(claim: Claim, numbers: CitationNumbers) -> str:
    """Render a claim with its citations and any verified quotations."""
    text: str = " ".join(claim.text.split()) + numbers.cite(claim.passage_ids)
    quote: PassageQuote
    for quote in claim.quotes:
        excerpt: str = escape_excerpt(" ".join(quote.text.split()))
        text += f" “{excerpt}”{numbers.cite([quote.passage_id])}"
    return text


def render_claims(claims: list[Claim], numbers: CitationNumbers) -> str:
    """
    Render claims as bullets with numbered citations.
    """
    return "\n".join(f"- {render_cited_claim(claim, numbers)}" for claim in claims)


def list_detail_sections(
    report: WriterReport,
    assessment: SampleAssessment,
) -> list[tuple[str, list[Claim]]]:
    """Return detailed coverage sections in reading order."""
    sections: list[tuple[str, list[Claim]]] = []
    if assessment.mode is AnswerMode.COMPARISON:
        sections.extend([
            ("Where coverage overlaps", report.overlap),
            ("Where coverage differs", report.differences),
        ])
    sections.extend([
        ("Attributed accounts", report.accounts),
        ("Reporting discrepancies", report.discrepancies),
        ("Timeline", report.timeline),
    ])
    return sections


def render_limitations(
    assessment: SampleAssessment,
    failed_reads: list[SourceAccessOutcome],
    notes: tuple[str, ...] = (),
) -> str:
    """
    State the sample counts, thin sides, and every failed article plainly.
    """
    lines: list[str] = [f"- Sample: {assessment.sample_statement}."]
    for group in assessment.thin_groups:
        lines.append(
            f"- The {group.value} sample is below the usual minimum "
            "(2 reporting articles from 2 outlets), so treat this comparison "
            "with caution."
        )
    lines.extend(render_failed_reads(failed_reads))
    lines.extend(f"- {note}" for note in notes)
    return "\n".join(lines)


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
        excerpt: str = citations.excerpt(article)
        if excerpt:
            lines.append(f"\n{' ' * (len(str(number)) + 2)}> {excerpt}")
    return "\n".join(lines)


def normalize_claim_text(text: str) -> str:
    """Compare whole words regardless of casing, punctuation, or whitespace."""
    return " " + re.sub(r"\W+", " ", text.casefold()).strip() + " "


def render_followup(
    report: WriterReport,
    assessment: SampleAssessment,
    articles: tuple[ArticleRecord, ...],
    failed_reads: list[SourceAccessOutcome],
    previous_answers: tuple[str, ...],
) -> str:
    """Render new analysis and detailed sections with citations and limitations."""
    previous_text: str = normalize_claim_text("\n".join(previous_answers))
    citations: CitationNumbers = CitationNumbers(articles)
    seen: set[str] = set()

    def select_new_claims(claims: list[Claim]) -> list[Claim]:
        """Exclude previously shown claims and duplicates across sections."""
        fresh: list[Claim] = []
        for claim in claims:
            normalized: str = normalize_claim_text(claim.text)
            if normalized not in previous_text and normalized not in seen:
                seen.add(normalized)
                fresh.append(claim)
        return fresh

    sections: list[str] = []
    analysis: list[Claim] = select_new_claims(report.summary)
    if analysis:
        sections.append(" ".join(render_cited_claim(claim, citations) for claim in analysis))
    for heading, claims in list_detail_sections(report, assessment):
        fresh: list[Claim] = select_new_claims(claims)
        if fresh:
            sections.append(f"## {heading}\n" + render_claims(fresh, citations))
    if not sections:
        sections.append("I couldn’t verify any additional details from the collected articles.")
    notes: tuple[str, ...] = (assessment.reason,) if assessment.reason else ()
    sections.append("## Limitations\n" + render_limitations(assessment, failed_reads, notes))
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
    Render a short briefing or a detailed report with citations and excerpts.
    """
    numbers: CitationNumbers | None = CitationNumbers(articles) if detailed else None
    comparing: bool = assessment.mode is AnswerMode.COMPARISON
    sections: list[str] = []
    if numbers is None:
        sentences: list[str] = [" ".join(claim.text.split()) for claim in report.summary]
        if assessment.reason:
            sentences.append(assessment.reason)
        elif assessment.thin_groups:
            sentences.append("This comparison draws on a small sample.")
        sentences.extend(notes)
        sections.append(" ".join(sentences))
    else:
        if not comparing:
            sections.append(f"> {assessment.reason}")
        sections.append(
            "## What the coverage reports\n" + render_claims(report.summary, numbers)
        )
    if comparing and alignment:
        rows: list[str] = [
            "| Aspect | Liberal outlets | Conservative outlets |",
            "| --- | --- | --- |",
        ]
        for row in alignment:
            rows.append(
                f"| {row.aspect} | {describe_treatment(row.liberal, numbers)} "
                f"| {describe_treatment(row.conservative, numbers)} |"
            )
        table: str = "\n".join(rows)
        sections.append(f"## How the coverage compares\n{table}" if detailed else table)
    if numbers is None:
        return "\n\n".join(sections)
    for heading, claims in list_detail_sections(report, assessment):
        if claims:
            sections.append(f"## {heading}\n" + render_claims(claims, numbers))
    sections.append(
        "## Limitations\n" + render_limitations(assessment, failed_reads, notes)
    )
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


def render_event_options(
    events: list[EventCandidate],
    window: tuple[date, date],
    maximum: int = 3,
) -> str:
    """
    Render attributed event choices or suggest a broader query when the list is empty.
    """
    lines: list[str] = []
    for number, event in enumerate(events[:maximum], start=1):
        others: list[str] = [
            outlet_display_name(outlet) for outlet in event.outlet_ids
            if outlet != event.headline_outlet
        ]
        dates: str = f"{event.first_date:%b} {event.first_date.day}"
        if event.last_date != event.first_date:
            dates += f" to {event.last_date:%b} {event.last_date.day}"
        title: str = " ".join(event.headline.split())
        headline: str = re.sub(r"([\\`*_\[\]<>])", r"\\\1", title)
        question_text: str = (
            f"How did different outlets cover “{title}” "
            f"from {window[0].isoformat()} to {window[1].isoformat()}?"
        )
        selection: str = quote(question_text, safe="")
        attribution: str = f" Also reported by {', '.join(others)}." if others else ""
        lines.append(
            f"{number}. {outlet_display_name(event.headline_outlet)} headline: "
            f"“{headline}”{attribution} ({dates}) "
            f"[Compare story {number}](#compare-event={selection}&headline={quote(title, safe='')})"
        )
    return "\n".join(lines) if lines else "Try a broader location or a wider date range."
