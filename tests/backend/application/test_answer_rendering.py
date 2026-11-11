"""
Behavior tests for rendering the final answer and checking its citations.

These tests check the application's Markdown, including how it reports
limitations, formats the comparison table, and validates evidence references."""

from backend.sources.constants import ArticleType
from backend.sources.access import SourceAccessOutcome
from backend.agents.researcher_findings import SourceGroup
from backend.agents.writer.schemas import Claim, WriterReport
from backend.application.answer.sample_assessment import assess_sample
from backend.agents.lead.schemas import AspectAlignment, AspectTreatment
from backend.application.answer.answer_rendering import (
    find_report_problems,
    render_answer,
    render_no_evidence_answer,
)


def assess(liberal, conservative):
    """
    Assess a sample made of the given articles per group.
    """
    return assess_sample(
        {SourceGroup.LIBERAL: liberal, SourceGroup.CONSERVATIVE: conservative}
    )


def alignment_for(liberal_article, conservative_article) -> list[AspectAlignment]:
    """
    Build one aligned aspect backed by one passage from each side.
    """
    return [
        AspectAlignment(
            aspect="Police response",
            liberal=AspectTreatment(
                state="central_focus",
                note="Led with injuries.",
                passage_ids=[liberal_article.passages[0].passage_id],
            ),
            conservative=AspectTreatment(state="not_in_sample"),
        )
    ]


def test_claims_render_with_numbered_citations_and_a_source_list(
    make_article,
) -> None:
    """
    Each cited article gets a number and appears in the sources list with its URL.
    """
    liberal = make_article("npr")
    conservative = make_article("fox")
    report = WriterReport(
        summary=[
            Claim(
                text="Protesters gathered in Paris.",
                passage_ids=[
                    liberal.passages[0].passage_id,
                    liberal.passages[1].passage_id,
                ],
            ),
            Claim(
                text="Police later issued a statement.",
                passage_ids=[liberal.passages[1].passage_id],
            ),
        ],
        differences=[
            Claim(
                text="Fox emphasised property damage.",
                passage_ids=[conservative.passages[1].passage_id],
            )
        ],
    )

    answer = render_answer(
        report=report,
        alignment=alignment_for(liberal, conservative),
        assessment=assess((liberal,), (conservative,)),
        articles=(liberal, conservative),
        failed_reads=[],
        detailed=True,
    )

    assert "Protesters gathered in Paris. [1]" in answer
    assert "Protesters gathered in Paris. [1][1]" not in answer
    assert "Police later issued a statement. [1]" in answer
    assert "Fox emphasised property damage. [2]" in answer
    assert "| Police response | Central focus: Led with injuries. [1] | Not in the sampled articles |" in answer
    assert f"{liberal.canonical_url}" in answer
    assert f"{conservative.canonical_url}" in answer


def test_summary_only_report_claiming_differences_is_a_problem(
    make_article,
) -> None:
    """
    The Writer may not claim divergence when one side has no articles.
    """
    liberal = make_article("npr")
    report = WriterReport(
        summary=[Claim(text="Facts.", passage_ids=[liberal.passages[0].passage_id])],
        differences=[
            Claim(text="They differ.", passage_ids=[liberal.passages[0].passage_id])
        ],
    )

    problems = find_report_problems(
        report=report,
        known_passage_ids={liberal.passages[0].passage_id},
        assessment=assess((liberal,), ()),
    )

    assert problems != []


def test_limitations_state_failed_articles_and_unequal_samples(
    make_article,
) -> None:
    """
    Failed articles, unequal counts, and thin samples are stated plainly.
    """
    liberal_a = make_article("npr")
    liberal_b = make_article("nbc")
    liberal_c = make_article("abc")
    conservative = make_article("fox")
    report = WriterReport(
        summary=[Claim(text="x", passage_ids=[liberal_a.passages[0].passage_id])]
    )

    answer = render_answer(
        report=report,
        alignment=[],
        assessment=assess((liberal_a, liberal_b, liberal_c), (conservative,)),
        articles=(liberal_a, liberal_b, liberal_c, conservative),
        failed_reads=[SourceAccessOutcome(outlet_id="nypost", status="paywall")],
        detailed=True,
    )

    assert "3 liberal articles from 3 outlets" in answer
    assert "1 conservative article from 1 outlet" in answer
    assert "New York Post" in answer
    assert "paywall" in answer.lower()
    assert "below the usual minimum" in answer


def test_opinion_articles_are_labelled_in_the_source_list(make_article) -> None:
    """
    Opinion pieces are identified so readers do not mistake them for reporting.
    """
    liberal = make_article("npr", article_type=ArticleType.OPINION)
    conservative = make_article("fox")
    report = WriterReport(
        summary=[Claim(text="x", passage_ids=[liberal.passages[0].passage_id])]
    )

    answer = render_answer(
        report=report,
        alignment=[],
        assessment=assess((liberal,), (conservative,)),
        articles=(liberal, conservative),
        failed_reads=[],
        detailed=True,
    )

    assert "(opinion)" in answer


def test_no_evidence_answer_says_nothing_was_retrieved() -> None:
    """
    When nothing could be read, the answer says so plainly and compares nothing.
    """
    answer = render_no_evidence_answer(
        reason="No articles could be retrieved from either side.",
        failed_reads=[],
    )

    assert "No articles could be retrieved from either side." in answer


def test_detailed_sections_are_allowed_only_for_detailed_reports_with_both_sides(
    make_article,
) -> None:
    """
    A briefing rejects detailed sections, and a one-sided summary rejects discrepancies.
    """
    liberal = make_article("npr")
    claim = Claim(text="Figures differ.", passage_ids=[liberal.passages[0].passage_id])
    known = {liberal.passages[0].passage_id}
    report = WriterReport(summary=[claim], discrepancies=[claim], timeline=[claim])

    both_sides = assess([liberal], [make_article("fox")])
    one_side = assess([liberal], [])

    assert find_report_problems(report, known, both_sides, detailed=True) == []
    assert any("briefing" in p for p in find_report_problems(report, known, both_sides))
    assert any("discrepancies" in p for p in find_report_problems(report, known, one_side, detailed=True))
