"""
Behavior tests for assessing the collected sample and choosing the answer mode.

The mode is decided here, in code, so the Writer cannot compare coverage when
one side has no usable articles.
"""

from backend.agents.researcher_findings import SourceGroup
from backend.sources.constants import ArticleType
from backend.application.sample_assessment import AnswerMode, assess_sample


def test_balanced_sample_meeting_the_floor_compares_without_qualification(
    make_article,
) -> None:
    """
    Two reporting articles from two outlets per side is a full comparison.
    """
    assessment = assess_sample(
        {
            SourceGroup.LIBERAL: (make_article("npr"), make_article("nbc")),
            SourceGroup.CONSERVATIVE: (make_article("fox"), make_article("nypost")),
        }
    )

    assert assessment.mode is AnswerMode.COMPARISON
    assert assessment.thin_groups == ()


def test_unequal_counts_are_stated_and_not_trimmed(make_article) -> None:
    """
    A 3 versus 2 sample is compared as found and the counts are stated.
    """
    assessment = assess_sample(
        {
            SourceGroup.LIBERAL: (
                make_article("npr"),
                make_article("nbc"),
                make_article("abc"),
            ),
            SourceGroup.CONSERVATIVE: (make_article("fox"), make_article("nypost")),
        }
    )

    assert assessment.mode is AnswerMode.COMPARISON
    assert "3 liberal articles from 3 outlets" in assessment.sample_statement
    assert "2 conservative articles from 2 outlets" in assessment.sample_statement


def test_side_below_the_floor_is_compared_but_marked_thin(make_article) -> None:
    """
    One conservative article is still compared, but flagged as thin.
    """
    assessment = assess_sample(
        {
            SourceGroup.LIBERAL: (make_article("npr"), make_article("nbc")),
            SourceGroup.CONSERVATIVE: (make_article("fox"),),
        }
    )

    assert assessment.mode is AnswerMode.COMPARISON
    assert assessment.thin_groups == (SourceGroup.CONSERVATIVE,)


def test_opinion_articles_do_not_count_toward_the_floor(make_article) -> None:
    """
    Only reporting articles satisfy the floor; opinion pieces are kept apart.
    """
    assessment = assess_sample(
        {
            SourceGroup.LIBERAL: (make_article("npr"), make_article("nbc")),
            SourceGroup.CONSERVATIVE: (
                make_article("fox"),
                make_article("nypost", article_type=ArticleType.OPINION),
            ),
        }
    )

    assert assessment.thin_groups == (SourceGroup.CONSERVATIVE,)


def test_side_with_no_articles_switches_to_summary_with_a_plain_reason(
    make_article,
) -> None:
    """
    With zero conservative articles only an objective summary is allowed.
    """
    assessment = assess_sample(
        {
            SourceGroup.LIBERAL: (make_article("npr"), make_article("nbc")),
            SourceGroup.CONSERVATIVE: (),
        }
    )

    assert assessment.mode is AnswerMode.SUMMARY_ONLY
    assert "conservative" in assessment.reason.lower()


def test_no_articles_on_either_side_means_no_evidence() -> None:
    """
    Nothing retrieved on either side gives no summary and no comparison.
    """
    assessment = assess_sample(
        {SourceGroup.LIBERAL: (), SourceGroup.CONSERVATIVE: ()}
    )

    assert assessment.mode is AnswerMode.NO_EVIDENCE
