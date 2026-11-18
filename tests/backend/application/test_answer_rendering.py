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
    assert "**Liberal coverage:** Main focus at NPR online news [1]. Led with injuries." in answer
    assert "**Conservative coverage:** Not found in the sampled articles." in answer
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


def test_no_limitations_section_is_rendered(make_article) -> None:
    """
    Failed reads, unequal counts, and thin samples no longer get a Limitations section.
    """
    liberal_a = make_article("npr")
    liberal_b = make_article("nbc")
    liberal_c = make_article("abc")
    conservative = make_article("fox")
    report = WriterReport(
        summary=[Claim(text="x", passage_ids=[liberal_a.passages[0].passage_id])]
    )

    for detailed in (True, False):
        answer = render_answer(
            report=report,
            alignment=[],
            assessment=assess((liberal_a, liberal_b, liberal_c), (conservative,)),
            articles=(liberal_a, liberal_b, liberal_c, conservative),
            failed_reads=[SourceAccessOutcome(outlet_id="nypost", status="paywall")],
            detailed=detailed,
        )

        assert "Limitations" not in answer
        assert "below the usual minimum" not in answer
        assert "New York Post" not in answer


def test_a_side_with_no_articles_is_stated_in_one_plain_line(make_article) -> None:
    """
    The one caveat kept is that a side had nothing usable, so no comparison was made.
    """
    liberal = make_article("npr")
    report = WriterReport(
        summary=[Claim(text="Facts.", passage_ids=[liberal.passages[0].passage_id])]
    )

    answer = render_answer(
        report=report, alignment=[], assessment=assess((liberal,), ()),
        articles=(liberal,), failed_reads=[],
    )

    assert "No conservative articles could be retrieved" in answer
    assert "Choose another issue from the front page" in answer
    assert "*Sample: 1 liberal article from 1 outlet and 0 conservative articles from 0 outlets.*" in answer


def test_a_briefing_cites_its_sentences_and_comparison_cells_by_number(make_article) -> None:
    """
    Every claim carries an in-text number that points into the Sources list.
    """
    liberal = make_article("npr")
    conservative = make_article("fox")
    alignment = [
        AspectAlignment(
            aspect="Police response",
            liberal=AspectTreatment(
                state="central_focus", note="Led with injuries.",
                passage_ids=[liberal.passages[0].passage_id],
            ),
            conservative=AspectTreatment(
                state="incidental_mention", note="Noted the arrests.",
                passage_ids=[conservative.passages[0].passage_id],
            ),
        ),
        AspectAlignment(
            aspect="Economic cost",
            liberal=AspectTreatment(state="not_in_sample"),
            conservative=AspectTreatment(
                state="central_focus", passage_ids=[conservative.passages[1].passage_id],
            ),
        ),
    ]
    opening = Claim(
        text="Protests occurred.",
        passage_ids=[liberal.passages[0].passage_id],
        quotes=[{"text": "A specific excerpt", "passage_id": liberal.passages[0].passage_id}],
    )
    report = WriterReport(
        summary=[opening, opening],
        overlap=[Claim(
            text="Both outlets covered the police response.",
            passage_ids=[liberal.passages[0].passage_id, conservative.passages[0].passage_id],
        )],
        differences=[Claim(
            text="Fox gave the economic cost more attention.",
            passage_ids=[conservative.passages[1].passage_id],
        )],
    )

    answer = render_answer(
        report=report, alignment=alignment, assessment=assess((liberal,), (conservative,)),
        articles=(liberal, conservative), failed_reads=[],
    )

    body, sources = answer.split("## Sources\n", 1)
    assert body.startswith("Protests occurred. [1]\n\n")
    assert body.count("Protests occurred.") == 1
    assert "A specific excerpt" not in body
    assert "> A specific excerpt" in sources
    assert "**Liberal coverage:** Main focus at NPR online news [1]. Led with injuries." in answer
    assert "**Conservative coverage:** Mentioned by Fox News Digital [2]. Noted the arrests." in answer
    assert "### Economic cost" in answer
    assert (
        body.index("## Where coverage overlaps\nBoth outlets covered the police response. [1][2]")
        < body.index("## Where coverage differs\nFox gave the economic cost more attention. [2]")
        < body.index("## Coverage aspects")
    )


def test_without_aspects_no_contrast_or_difference_is_invented(make_article) -> None:
    """
    With no aspects to compare, no side lists and no claim about differences appear.
    """
    liberal = make_article("npr")
    conservative = make_article("fox")
    report = WriterReport(
        summary=[Claim(text="Both covered it.", passage_ids=[liberal.passages[0].passage_id])]
    )

    answer = render_answer(
        report=report, alignment=[], assessment=assess((liberal,), (conservative,)),
        articles=(liberal, conservative), failed_reads=[],
    )

    assert "No clear difference" not in answer
    assert "### Liberal outlets" not in answer


def test_aspect_overflow_keeps_single_outlet_focuses_available(make_article) -> None:
    """Show a few cards up front and keep additional main focuses available."""
    liberal = make_article("npr")
    conservative = make_article("fox")
    passage_id: str = liberal.passages[0].passage_id
    alignment: list[AspectAlignment] = [
        AspectAlignment(
            aspect=aspect,
            liberal=AspectTreatment(state="central_focus", passage_ids=[passage_id]),
            conservative=AspectTreatment(state="not_in_sample"),
        )
        for aspect in ("Public safety", "Aid access", "Regional diplomacy", "Border policy")
    ]
    answer: str = render_answer(
        report=WriterReport(summary=[Claim(text="Recent developments.", passage_ids=[passage_id])]),
        alignment=alignment,
        assessment=assess((liberal,), (conservative,)),
        articles=(liberal, conservative),
        failed_reads=[],
    )
    featured, remaining = answer.split("## More aspects", 1)
    assert featured.count("### ") == 3
    assert "### Border policy" in remaining
    assert "**Liberal coverage:** Main focus at NPR online news [1]." in remaining
    assert "**Conservative coverage:** Not found in the sampled articles." in remaining
    assert "*Sample: 1 liberal article from 1 outlet and 1 conservative article from 1 outlet.*" in remaining


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
