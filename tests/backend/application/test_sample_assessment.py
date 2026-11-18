"""
Behavior tests for assessing the collected sample and choosing the answer mode.

The mode is decided here, in code, so the Writer cannot compare coverage when
one side has no usable articles.
"""

from backend.agents.researcher_findings import SourceGroup
from backend.application.answer.sample_assessment import AnswerMode, assess_sample


def test_no_articles_on_either_side_means_no_evidence() -> None:
    """
    Nothing retrieved on either side gives no summary and no comparison.
    """
    assessment = assess_sample(
        {SourceGroup.LIBERAL: (), SourceGroup.CONSERVATIVE: ()}
    )

    assert assessment.mode is AnswerMode.NO_EVIDENCE
