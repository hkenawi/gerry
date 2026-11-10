"""
End-to-end behavior tests for one turn of the Lead, Researcher, Writer workflow.

A scripted model drives the real agents, tools, budget, validation, and renderer.
Only the model and the article sources are fakes, so these tests are offline.
"""

import pytest
import asyncio

from typing import Any

from backend.agents.lead.tools import check_brief
from backend.application.settings import Settings
from backend.application.turn.run_turn import run_turn
from backend.agents.researcher_findings import SourceGroup
from backend.interfaces.http.chat_contracts import ChatMessage
from backend.sources.access import ArticleReadResult, SourceAccessOutcome
from support.scripted_model import (
    FinalOutput,
    ModelCall,
    ScriptedModel,
    ToolCalls,
)
from backend.application.turn.failure_category import FailureCategory, describe_failure

WINDOW_ARGS: dict[str, Any] = {
    "event": "Paris protests",
    "start_date": "2026-11-01",
    "end_date": "2026-11-07",
    "focus_question": None,
}
MESSAGES: list[ChatMessage] = [
    ChatMessage(role="user", content="Compare coverage of the Paris protests.")
]


def success_result(article) -> ArticleReadResult:
    """
    Build a successful read result for an already-built article.
    """
    return ArticleReadResult(
        outcome=SourceAccessOutcome(outlet_id=article.outlet_id, status="success"),
        article=article,
    )


def failed_result(outlet_id: str, status: str) -> ArticleReadResult:
    """
    Build a failed read result.
    """
    return ArticleReadResult(
        outcome=SourceAccessOutcome(outlet_id=outlet_id, status=status)
    )


def findings_payload(group: SourceGroup, articles: list) -> dict[str, Any]:
    """
    Build researcher findings citing the first passage of each article.
    """
    return {
        "group": group.value,
        "article_ids": [str(article.article_id) for article in articles],
        "main_focuses": [
            {
                "aspect": "Police response",
                "article_id": str(article.article_id),
                "passage_ids": [article.passages[0].passage_id],
            }
            for article in articles
        ],
        "limitations": [],
    }


def lead_outcome() -> dict[str, Any]:
    """
    Build the Lead's final structured output: a clear brief.
    """
    return {
        "brief": {
            "status": "clear",
            "event": "Paris protests",
            "start_date": "2026-11-01",
            "end_date": "2026-11-07",
        }
    }


class Scenario:
    """
    Wires a scripted model to per-agent behavior for one test.
    """

    def __init__(self) -> None:
        """
        Start with a barrier proving the two researchers overlap in time.
        """
        self.barrier: asyncio.Barrier = asyncio.Barrier(2)
        self.lead_reply: Any = None
        self.researcher_replies: dict[SourceGroup, Any] = {}
        self.writer_replies: list[dict[str, Any]] = []
        self.writer_calls: list[ModelCall] = []
        self.model: ScriptedModel = ScriptedModel(self.dispatch)

    async def dispatch(self, call: ModelCall) -> Any:
        """
        Route a model call to the Lead, Researcher, or Writer script.
        """
        if "You are the Lead" in call.system_instructions:
            return self.lead_reply(call)
        if "You are the Writer" in call.system_instructions:
            self.writer_calls.append(call)
            index: int = min(len(self.writer_calls), len(self.writer_replies)) - 1
            return FinalOutput(self.writer_replies[index])
        group: SourceGroup = (
            SourceGroup.LIBERAL
            if "Source group: liberal" in call.input_text
            else SourceGroup.CONSERVATIVE
        )
        if not call.tool_results:
            await asyncio.wait_for(self.barrier.wait(), timeout=2)
        return self.researcher_replies[group](call)


def fan_out_then(alignment: list[dict[str, Any]], write_calls: int = 1):
    """
    Build a Lead script: research both groups in one turn, call the Writer tool,
    then finish with a clear brief.
    """

    def reply(call: ModelCall):
        """
        Fan out first, write next, and finish once writing has been attempted.
        """
        done: int = len(call.tool_results)
        if done == 0:
            return ToolCalls(
                [
                    ("research_liberal_coverage", WINDOW_ARGS),
                    ("research_conservative_coverage", WINDOW_ARGS),
                ]
            )
        if done < 2 + write_calls:
            return ToolCalls(
                [
                    (
                        "write_answer",
                        {"question": MESSAGES[0].content, "alignment": alignment},
                    )
                ]
            )
        return FinalOutput(lead_outcome())

    return reply


def search_read_then(urls_and_outlets, final: dict[str, Any]):
    """
    Build a Researcher script: search, read the given articles, then finish.
    """

    def reply(call: ModelCall):
        """
        Search first, read every article next, then return findings.
        """
        if not call.tool_results:
            return ToolCalls([("search_articles", {"query": "Paris protests"})])
        if len(call.tool_results) == 1:
            return ToolCalls(
                [
                    ("read_article", {"url": url, "outlet_id": outlet})
                    for url, outlet in urls_and_outlets
                ]
            )
        return FinalOutput(final)

    return reply


def writer_report(liberal_article, conservative_article) -> dict[str, Any]:
    """
    Build a valid Writer report citing one passage from each side.
    """
    return {
        "summary": [
            {
                "text": "Large protests took place in Paris.",
                "passage_ids": [liberal_article.passages[0].passage_id],
            }
        ],
        "differences": [
            {
                "text": "The conservative outlets stressed property damage.",
                "passage_ids": [conservative_article.passages[1].passage_id],
            }
        ],
    }


def alignment_for(liberal_article, conservative_article) -> list[dict[str, Any]]:
    """
    Build one aligned aspect backed by passages from both sides.
    """
    return [
        {
            "aspect": "Police response",
            "liberal": {
                "state": "central_focus",
                "note": "",
                "passage_ids": [liberal_article.passages[0].passage_id],
            },
            "conservative": {
                "state": "incidental_mention",
                "note": "",
                "passage_ids": [conservative_article.passages[0].passage_id],
            },
        }
    ]


@pytest.fixture
def articles(make_article) -> dict[str, Any]:
    """
    Build two articles per side, keyed by outlet.
    """
    return {
        outlet: make_article(outlet) for outlet in ("npr", "nbc", "fox", "nypost")
    }


def wire_full_scenario(scenario: Scenario, fake_sources, articles) -> None:
    """
    Script a complete run where every article is read successfully.
    """
    for outlet, article in articles.items():
        fake_sources.read_script[f"https://{outlet}.example/a"] = [
            success_result(article)
        ]
    liberal = [articles["npr"], articles["nbc"]]
    conservative = [articles["fox"], articles["nypost"]]
    scenario.lead_reply = fan_out_then(
        alignment_for(articles["npr"], articles["fox"])
    )
    scenario.researcher_replies = {
        SourceGroup.LIBERAL: search_read_then(
            [(f"https://{a.outlet_id}.example/a", a.outlet_id) for a in liberal],
            findings_payload(SourceGroup.LIBERAL, liberal),
        ),
        SourceGroup.CONSERVATIVE: search_read_then(
            [(f"https://{a.outlet_id}.example/a", a.outlet_id) for a in conservative],
            findings_payload(SourceGroup.CONSERVATIVE, conservative),
        ),
    }
    scenario.writer_replies = [writer_report(articles["npr"], articles["fox"])]


async def test_clear_request_fans_out_concurrently_and_returns_a_cited_comparison(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    Both researchers run at the same time and the answer cites saved sources.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    state = make_state()

    result = await run_turn(MESSAGES, state, scenario.model)

    assert result.failure is None
    assert "## Where coverage differs" in result.answer
    assert "[1]" in result.answer
    assert "## Sources" in result.answer
    agents = {record.agent for record in result.tool_calls}
    assert {"lead", "researcher_liberal", "researcher_conservative"} <= agents
    assert any(
        record.agent == "lead"
        and record.tool == "write_answer"
        and record.outcome == "success"
        for record in result.tool_calls
    )
    assignments: list[ModelCall] = [
        call
        for call in scenario.model.calls
        if "You are a Researcher" in call.system_instructions and not call.tool_results
    ]
    assert len(assignments) == 2
    assert all(len(call.input_items) == 1 for call in assignments)
    assert all("Compare coverage" not in call.input_text for call in assignments)
    brief, findings = state.store.load_research(state.conversation_id)
    assert brief.event == "Paris protests"
    assert {item.group for item in findings} == set(SourceGroup)


async def test_a_side_with_no_usable_articles_gets_a_summary_not_a_comparison(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    If every conservative article fails, the answer is an objective summary.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    for outlet in ("fox", "nypost"):
        fake_sources.read_script[f"https://{outlet}.example/a"] = [
            failed_result(outlet, "paywall")
        ]
    scenario.researcher_replies[SourceGroup.CONSERVATIVE] = search_read_then(
        [("https://fox.example/a", "fox"), ("https://nypost.example/a", "nypost")],
        {
            "group": "conservative",
            "article_ids": [],
            "main_focuses": [],
            "limitations": ["Every article was behind a paywall."],
        },
    )
    scenario.lead_reply = fan_out_then([])
    scenario.writer_replies = [
        {
            "summary": [
                {
                    "text": "Large protests took place in Paris.",
                    "passage_ids": [articles["npr"].passages[0].passage_id],
                }
            ]
        }
    ]

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    assert result.failure is None
    assert "No conservative articles could be retrieved" in result.answer
    assert "| Aspect |" not in result.answer
    assert "Where coverage differs" not in result.answer
    assert "Fox News Digital" in result.answer
    assert "paywall" in result.answer.lower()
    assert "summary_only" in scenario.writer_calls[0].input_text


async def test_writer_with_an_invalid_citation_gets_one_correction_attempt(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    An invented passage ID is corrected once and never shown to the reader.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    valid = writer_report(articles["npr"], articles["fox"])
    invalid = {"summary": [{"text": "Made up.", "passage_ids": ["bogus-passage"]}]}
    scenario.writer_replies = [invalid, valid]

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    assert len(scenario.writer_calls) == 2
    assert "bogus-passage" in scenario.writer_calls[1].input_text
    assert "bogus-passage" not in result.answer
    assert result.failure is None


async def test_writer_still_invalid_after_correction_returns_a_plain_failure(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    If the correction also fails, no invalid result is presented.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    invalid = {"summary": [{"text": "Made up.", "passage_ids": ["bogus-passage"]}]}
    scenario.writer_replies = [invalid, invalid]

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    assert result.failure is FailureCategory.INVALID_OUTPUT
    assert result.answer == describe_failure(FailureCategory.INVALID_OUTPUT).message
    assert "bogus-passage" not in result.answer


async def test_researcher_citing_an_unread_article_is_corrected_once(
    make_state,
    fake_sources,
    articles,
    make_article,
) -> None:
    """
    Findings that cite an article never read are rejected, then corrected.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    liberal = [articles["npr"], articles["nbc"]]
    invented = make_article("npr")
    good = findings_payload(SourceGroup.LIBERAL, liberal)
    bad = findings_payload(SourceGroup.LIBERAL, [invented])

    base = search_read_then(
        [(f"https://{a.outlet_id}.example/a", a.outlet_id) for a in liberal],
        bad,
    )

    def reply(call: ModelCall):
        """
        Return invalid findings first and corrected findings after rejection.
        """
        if len(call.tool_results) >= 3 and "rejected" in call.input_text:
            return FinalOutput(good)
        return base(call)

    scenario.researcher_replies[SourceGroup.LIBERAL] = reply
    state = make_state()

    result = await run_turn(MESSAGES, state, scenario.model)

    assert result.failure is None
    assert str(invented.article_id) not in str(state.findings[SourceGroup.LIBERAL])
    assert state.findings[SourceGroup.LIBERAL][0].article_ids == good["article_ids"]


async def test_exhausted_model_budget_returns_a_plain_research_limit_result(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    When the model-call budget runs out before any evidence exists, say so.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    state = make_state(Settings(max_model_calls=1))

    result = await run_turn(MESSAGES, state, scenario.model)

    assert result.failure is FailureCategory.RESEARCH_LIMIT_REACHED
    assert result.answer == describe_failure(
        FailureCategory.RESEARCH_LIMIT_REACHED
    ).message
    assert any(record.outcome == "failure" for record in result.tool_calls)


async def test_event_window_is_fixed_after_the_first_research_call(
    make_state,
) -> None:
    """
    A later call cannot move the publication window the first call set.
    """
    state = make_state()

    first, problem = check_brief(state, "Paris protests", "2026-11-01", "2026-11-07")
    second, second_problem = check_brief(
        state, "Paris protests", "2026-10-01", "2026-10-07"
    )

    assert problem is None and first is not None
    assert second is None
    assert "fixed" in second_problem


async def test_researcher_that_never_finishes_is_reported_and_does_not_stop_the_run(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    A Researcher stuck in a tool loop fails visibly while the other side finishes.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    scenario.researcher_replies[SourceGroup.CONSERVATIVE] = lambda call: ToolCalls(
        [("search_articles", {"query": "again"})]
    )
    scenario.lead_reply = fan_out_then([])
    scenario.writer_replies = [
        {
            "summary": [
                {
                    "text": "Large protests took place in Paris.",
                    "passage_ids": [articles["npr"].passages[0].passage_id],
                }
            ]
        }
    ]

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    assert result.failure is None
    assert "No conservative articles could be retrieved" in result.answer
    assert any(
        record.agent == "lead"
        and record.tool == "research_conservative_coverage"
        and record.outcome == "failure"
        for record in result.tool_calls
    )


async def test_lead_cannot_finish_a_clear_brief_without_writing_the_answer(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    A Lead that skips the Writer tool is told to call it and then succeeds.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    fan_out = fan_out_then(alignment_for(articles["npr"], articles["fox"]))

    def reply(call: ModelCall):
        """
        Finish early the first time, then write once corrected.
        """
        if len(call.tool_results) == 2 and "rejected" not in call.input_text:
            return FinalOutput(lead_outcome())
        return fan_out(call)

    scenario.lead_reply = reply

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    assert result.failure is None
    assert "## Sources" in result.answer


async def test_alignment_citing_the_wrong_group_is_returned_to_the_lead(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    A bad alignment never reaches the Writer; the Lead fixes it and retries.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    good = alignment_for(articles["npr"], articles["fox"])
    bad = alignment_for(articles["fox"], articles["fox"])
    sequence = [bad, good]

    def reply(call: ModelCall):
        """
        Research, write with a bad alignment, then write again with a good one.
        """
        done = len(call.tool_results)
        if done == 0:
            return fan_out_then(good)(call)
        if done in (2, 3):
            return ToolCalls(
                [
                    (
                        "write_answer",
                        {"question": "q", "alignment": sequence[done - 2]},
                    )
                ]
            )
        return FinalOutput(lead_outcome())

    scenario.lead_reply = reply

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    assert result.failure is None
    assert len(scenario.writer_calls) == 1
    writes = [r for r in result.tool_calls if r.tool == "write_answer"]
    assert [record.outcome for record in writes] == ["failure", "success"]


async def test_writer_tool_calls_are_capped_per_request(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    After two failed Writer attempts a third call is refused without running it.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    invalid = {"summary": [{"text": "Made up.", "passage_ids": ["bogus-passage"]}]}
    scenario.writer_replies = [invalid]
    scenario.lead_reply = fan_out_then(
        alignment_for(articles["npr"], articles["fox"]),
        write_calls=3,
    )

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    assert len(scenario.writer_calls) == 4
    assert result.failure is FailureCategory.INVALID_OUTPUT


@pytest.mark.parametrize("max_model_calls", [7, 8])
async def test_spent_budget_after_research_still_yields_a_noted_partial_answer(
    make_state,
    fake_sources,
    articles,
    max_model_calls: int,
) -> None:
    """Use saved evidence when the Lead or Writer reaches the model-call limit."""
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    state = make_state(Settings(max_model_calls=max_model_calls))

    result = await run_turn(MESSAGES, state, scenario.model)

    assert result.failure is None
    assert "research limit was reached" in result.answer
    assert "This partial result lists the available headlines." in result.answer
    assert "## Sources" in result.answer
    assert scenario.writer_calls == []


async def test_lead_cannot_start_one_research_group_on_its_own(make_state) -> None:
    """Reject an incomplete fan-out before it starts a Researcher."""
    def reply(call: ModelCall) -> ToolCalls | FinalOutput:
        """Keep requesting an incomplete initial fan-out."""
        if "You are the Lead" in call.system_instructions:
            return ToolCalls([("research_liberal_coverage", WINDOW_ARGS)])
        return FinalOutput(findings_payload(SourceGroup.LIBERAL, []))

    model: ScriptedModel = ScriptedModel(reply)
    result = await run_turn(MESSAGES, make_state(), model)

    assert result.failure is FailureCategory.INVALID_OUTPUT
    assert all("You are the Lead" in call.system_instructions for call in model.calls)


async def test_writer_can_return_an_evidence_gap_to_the_lead(
    make_state, fake_sources, articles,
) -> None:
    """Give the Lead the missing evidence request before storing any answer."""
    scenario: Scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    scenario.writer_replies.insert(0, {"evidence_gap": "Check the timing of police response."})
    scenario.lead_reply = fan_out_then(
        alignment_for(articles["npr"], articles["fox"]), write_calls=2,
    )

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    assert result.failure is None
    assert any(
        "Check the timing of police response." in call.input_text
        for call in scenario.model.calls if "You are the Lead" in call.system_instructions
    )
    assert "## Sources" in result.answer
