"""
Render the reader-facing Markdown answer and verify its citations.

The Writer supplies claims tied to passage IDs; this module resolves each ID to
a saved article, numbers the citations, builds the comparison table, and states
limitations such as failed articles and unequal samples. Invalid citations are
reported as problems so they can be corrected and are never shown to readers.
"""

from backend.sources.articles import ArticleRecord
from backend.agents.lead.schemas import AspectAlignment, AspectTreatment, CoverageState
from backend.sources.access import SourceAccessOutcome
from backend.sources.constants import ArticleType, SourceAccessStatus
from backend.agents.researcher_findings import SourceGroup
from backend.agents.writer.schemas import Claim, WriterReport
from backend.application.sample_assessment import AnswerMode, SampleAssessment
from backend.application.outlet_assignments import outlet_display_name

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
        self._numbers: dict[str, int] = {}

    def cite(self, passage_ids: list[str]) -> str:
        """
        Return the numbered markers for the passages, assigning new numbers.
        """
        markers: list[str] = []
        for passage_id in passage_ids:
            article_id: str = article_id_of(passage_id)
            if article_id not in self._numbers:
                self._numbers[article_id] = len(self._numbers) + 1
            marker: str = f"[{self._numbers[article_id]}]"
            if marker not in markers:
                markers.append(marker)
        return " " + "".join(markers) if markers else ""

    def sources(self) -> list[ArticleRecord]:
        """
        Return cited articles ordered by their citation number.
        """
        ordered: list[str] = sorted(self._numbers, key=self._numbers.__getitem__)
        return [self._articles[article_id] for article_id in ordered]


def collect_passage_ids(
    report: WriterReport,
    alignment: list[AspectAlignment],
) -> list[str]:
    """
    List every passage ID cited by the report and the alignment table.
    """
    claims: list[Claim] = [*report.summary, *report.overlap, *report.differences]
    passage_ids: list[str] = [
        passage_id for claim in claims for passage_id in claim.passage_ids
    ]
    for row in alignment:
        passage_ids.extend(row.liberal.passage_ids)
        passage_ids.extend(row.conservative.passage_ids)
    return passage_ids


def find_report_problems(
    report: WriterReport,
    alignment: list[AspectAlignment],
    articles: tuple[ArticleRecord, ...],
    assessment: SampleAssessment,
) -> list[str]:
    """
    List reasons the report cannot be shown, for a correction attempt.
    """
    known: set[str] = {
        passage.passage_id for article in articles for passage in article.passages
    }
    problems: list[str] = [
        f"Passage ID {passage_id!r} does not exist in the collected articles."
        for passage_id in dict.fromkeys(collect_passage_ids(report, alignment))
        if passage_id not in known
    ]
    if assessment.mode is not AnswerMode.COMPARISON and (
        report.overlap or report.differences
    ):
        problems.append(
            "Do not describe overlap or differences: one side has no articles, "
            "so only an objective summary is allowed."
        )
    return problems


def find_alignment_problems(
    alignment: list[AspectAlignment],
    articles_by_group: dict[SourceGroup, tuple[ArticleRecord, ...]],
) -> list[str]:
    """
    List alignment citations that do not belong to the group they describe.
    """
    problems: list[str] = []
    for row in alignment:
        for group, treatment in (
            (SourceGroup.LIBERAL, row.liberal),
            (SourceGroup.CONSERVATIVE, row.conservative),
        ):
            allowed: set[str] = {
                passage.passage_id
                for article in articles_by_group[group]
                for passage in article.passages
            }
            problems.extend(
                f"Aspect {row.aspect!r} cites passage {passage_id!r}, which is "
                f"not from a {group.value} article you were given."
                for passage_id in treatment.passage_ids
                if passage_id not in allowed
            )
    return problems


def describe_treatment(treatment: AspectTreatment, numbers: CitationNumbers) -> str:
    """
    Render one table cell: the coverage label, optional note, and citations.
    """
    text: str = COVERAGE_LABELS[treatment.state]
    if treatment.note:
        text += f": {treatment.note}"
    text += numbers.cite(treatment.passage_ids)
    return text.replace("|", "/").replace("\n", " ")


def render_claims(claims: list[Claim], numbers: CitationNumbers) -> str:
    """
    Render claims as bullets with numbered citations.
    """
    return "\n".join(
        f"- {claim.text}{numbers.cite(claim.passage_ids)}" for claim in claims
    )


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


def render_sources(articles: list[ArticleRecord]) -> str:
    """
    Render the numbered source list with outlet, title, link, and type.
    """
    lines: list[str] = []
    for number, article in enumerate(articles, start=1):
        line: str = (
            f"{number}. {outlet_display_name(article.outlet_id)}: "
            f"[{article.title}]({article.canonical_url})"
        )
        if article.published_at is not None:
            line += f", {article.published_at.isoformat()}"
        if article.article_type is not ArticleType.REPORTING:
            line += f" ({article.article_type.value})"
        lines.append(line)
    return "\n".join(lines)


def render_answer(
    report: WriterReport,
    alignment: list[AspectAlignment],
    assessment: SampleAssessment,
    articles: tuple[ArticleRecord, ...],
    failed_reads: list[SourceAccessOutcome],
    notes: tuple[str, ...] = (),
) -> str:
    """
    Render the full Markdown answer for a comparison or an objective summary.
    """
    numbers: CitationNumbers = CitationNumbers(articles)
    comparing: bool = assessment.mode is AnswerMode.COMPARISON
    sections: list[str] = []
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
        sections.append("## How the coverage compares\n" + "\n".join(rows))
    if comparing and report.overlap:
        sections.append(
            "## Where coverage overlaps\n" + render_claims(report.overlap, numbers)
        )
    if comparing and report.differences:
        sections.append(
            "## Where coverage differs\n" + render_claims(report.differences, numbers)
        )
    sections.append(
        "## Limitations\n" + render_limitations(assessment, failed_reads, notes)
    )
    sections.append("## Sources\n" + render_sources(numbers.sources()))
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
