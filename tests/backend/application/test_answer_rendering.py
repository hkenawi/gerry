"""
Behavior tests for rendering the final answer and checking its citations.

Application code, not the model, produces the Markdown so that citations,
the comparison table, and limitations are consistent and verifiable.
"""

from backend.agents.lead.schemas import AspectAlignment, AspectTreatment
from backend.agents.writer.schemas import Claim, WriterReport
from backend.agents.researcher_findings import SourceGroup
from backend.application.answer_rendering import (
    find_alignment_problems,
    find_report_problems,
    render_answer,
    render_no_evidence_answer,
)
from backend.application.sample_assessment import assess_sample
from backend.sources.access import SourceAccessOutcome
from backend.sources.constants import ArticleType


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
                passage_ids=[liberal.passages[0].passage_id],
            )
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
    )

    assert "Protesters gathered in Paris. [1]" in answer
    assert "Fox emphasised property damage. [2]" in answer
    assert f"{liberal.canonical_url}" in answer
    assert f"{conservative.canonical_url}" in answer


def test_the_same_article_cited_twice_reuses_one_number(make_article) -> None:
    """
    Citation numbers identify articles, not individual passages.
    """
    liberal = make_article("npr")
    conservative = make_article("fox")
    report = WriterReport(
        summary=[
            Claim(text="First.", passage_ids=[liberal.passages[0].passage_id]),
            Claim(text="Second.", passage_ids=[liberal.passages[1].passage_id]),
        ]
    )

    answer = render_answer(
        report=report,
        alignment=[],
        assessment=assess((liberal,), (conservative,)),
        articles=(liberal, conservative),
        failed_reads=[],
    )

    assert "First. [1]" in answer
    assert "Second. [1]" in answer


def test_citations_to_unknown_passages_are_reported_as_problems(
    make_article,
) -> None:
    """
    Invented passage IDs are detected so a correction attempt can fix them.
    """
    liberal = make_article("npr")
    report = WriterReport(
        summary=[Claim(text="Made up.", passage_ids=["not-a-real-passage"])]
    )

    problems = find_report_problems(
        report=report,
        alignment=[],
        articles=(liberal,),
        assessment=assess((liberal,), (make_article("fox"),)),
    )

    assert any("not-a-real-passage" in problem for problem in problems)


def test_comparison_table_shows_each_sides_coverage_state(make_article) -> None:
    """
    The table lists each aspect with a plain label for each group.
    """
    liberal = make_article("npr")
    conservative = make_article("fox")
    report = WriterReport(
        summary=[Claim(text="x", passage_ids=[liberal.passages[0].passage_id])]
    )

    answer = render_answer(
        report=report,
        alignment=alignment_for(liberal, conservative),
        assessment=assess((liberal,), (conservative,)),
        articles=(liberal, conservative),
        failed_reads=[],
    )

    assert "| Police response |" in answer
    assert "Central focus" in answer
    assert "Not in the sampled articles" in answer


def test_summary_only_mode_has_no_comparison_and_explains_why(
    make_article,
) -> None:
    """
    With one side empty the answer is an objective summary with the reason.
    """
    liberal = make_article("npr")
    report = WriterReport(
        summary=[Claim(text="Facts.", passage_ids=[liberal.passages[0].passage_id])]
    )

    answer = render_answer(
        report=report,
        alignment=[],
        assessment=assess((liberal,), ()),
        articles=(liberal,),
        failed_reads=[],
    )

    assert "No conservative articles could be retrieved" in answer
    assert "| Aspect |" not in answer
    assert "Where coverage differs" not in answer


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
        alignment=[],
        articles=(liberal,),
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


def test_alignment_citing_the_other_groups_passage_is_a_problem(
    make_article,
) -> None:
    """
    A liberal alignment cell may not cite a conservative article's passage.
    """
    liberal = make_article("npr")
    conservative = make_article("fox")
    alignment = [
        AspectAlignment(
            aspect="Police response",
            liberal=AspectTreatment(
                state="central_focus",
                passage_ids=[conservative.passages[0].passage_id],
            ),
            conservative=AspectTreatment(state="not_in_sample"),
        )
    ]

    problems = find_alignment_problems(
        alignment,
        {SourceGroup.LIBERAL: (liberal,), SourceGroup.CONSERVATIVE: (conservative,)},
    )

    assert len(problems) == 1
    assert "liberal" in problems[0]


def test_research_limit_note_appears_in_the_limitations(make_article) -> None:
    """
    A note passed by the caller is stated plainly in the limitations section.
    """
    liberal = make_article("npr")
    report = WriterReport(
        summary=[Claim(text="x", passage_ids=[liberal.passages[0].passage_id])]
    )

    answer = render_answer(
        report=report,
        alignment=[],
        assessment=assess((liberal,), (make_article("fox"),)),
        articles=(liberal,),
        failed_reads=[],
        notes=("The research limit was reached.",),
    )

    assert "- The research limit was reached." in answer
