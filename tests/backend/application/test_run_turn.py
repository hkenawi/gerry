"""
End-to-end behavior tests for one turn of the Lead, Researcher, Writer workflow.

A scripted model drives the real agents, tools, budget, validation, and renderer.
Only the model and the article sources are fakes, so these tests are offline.
"""

import json
import httpx
import pytest
import asyncio

from typing import Any
from datetime import date, timedelta
from openai import APIConnectionError
from urllib.parse import parse_qs, unquote

from backend.sources.articles import ArticleRecord
from backend.agents.lead.tools import check_brief
from backend.application.settings import Settings
from backend.application.turn.run_turn import run_turn
from backend.agents.researcher_findings import SourceGroup
from backend.interfaces.http.chat_contracts import ChatMessage
from backend.sources.access import (
    ArticleCandidate,
    ArticleReadResult,
    ArticleSearchResult,
    SourceAccessOutcome,
)
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
    ChatMessage(
        role="user",
        content="How did different outlets cover “Paris protests” from 2026-11-01 to 2026-11-07?",
    )
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


async def test_clear_request_fans_out_concurrently_and_returns_a_brief_comparison(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    Both researchers run together and the first answer presents a compact briefing.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    scenario.writer_replies[0]["summary"].append({
        "text": "The conservative outlets put more emphasis on property damage.",
        "passage_ids": [articles["fox"].passages[1].passage_id],
    })
    state = make_state()

    result = await run_turn(MESSAGES, state, scenario.model)

    assert result.failure is None
    body, sources = result.answer.split("\n\n## Sources\n")
    summary, table, legend = body.split("\n\n")
    assert summary == (
        "Large protests took place in Paris. [1] The conservative outlets put more emphasis "
        "on property damage. [2]"
    )
    assert table.splitlines() == [
        "| Aspect | Liberal outlets | Conservative outlets |", "| --- | --- | --- |",
        "| Police response | ●●● central [1] | ●○○ brief [2] |",
    ]
    assert legend.startswith("*●●● central focus")
    assert sources.startswith("1. ")
    assert "## Limitations" not in result.answer
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
    assert all("How did different outlets" not in call.input_text for call in assignments)
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
    assert "## Limitations" not in result.answer
    assert "### Liberal outlets" in result.answer
    assert (
        "### Conservative outlets\n- No articles could be retrieved from conservative outlets."
        in result.answer
    )
    assert "## Sources" in result.answer
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


def test_undated_research_uses_a_month_and_followups_keep_that_window(make_state) -> None:
    """Resolve default dates on the first call and reuse them for later turns."""
    state = make_state()
    first, problem = check_brief(state, "Paris protests", None, None, today=date(2026, 11, 11))
    followup, followup_problem = check_brief(
        state, "Paris protests", None, None, today=date(2026, 11, 12),
    )

    assert problem is None and followup_problem is None
    assert first == followup == (date(2026, 10, 11), date(2026, 11, 11))


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
    assert "| Aspect | Liberal outlets | Conservative outlets |" in result.answer


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
    assert "| Aspect | Liberal outlets | Conservative outlets |" in result.answer


def provider_outage(call: ModelCall):
    """
    Fail the way an unreachable model provider does.
    """
    raise APIConnectionError(request=httpx.Request("POST", "https://model.example"))


async def test_model_outage_in_the_lead_returns_a_retryable_model_failure(
    make_state,
) -> None:
    """
    A provider error is reported as an unavailable model, not an unexpected failure.
    """
    scenario = Scenario()
    scenario.lead_reply = provider_outage

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    assert result.failure is FailureCategory.MODEL_UNAVAILABLE
    assert result.answer == describe_failure(FailureCategory.MODEL_UNAVAILABLE).message


async def test_model_outage_in_one_researcher_leaves_a_partial_answer(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    One side's model failure is recorded while the other side still produces an answer.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    scenario.researcher_replies[SourceGroup.CONSERVATIVE] = provider_outage
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
    scenario.lead_reply = fan_out_then([])

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    assert result.failure is None
    assert "No conservative articles could be retrieved" in result.answer
    assert any(
        record.tool == "research_conservative_coverage" and record.outcome == "failure"
        for record in result.tool_calls
    )


async def test_request_deadline_expiring_returns_a_research_limit_result(make_state) -> None:
    """
    A model call still running at the deadline ends the turn with a plain result.
    """
    async def stalled(call: ModelCall):
        """
        Hold the Lead's model call past the one-second deadline.
        """
        await asyncio.sleep(5)

    result = await run_turn(
        MESSAGES, make_state(Settings(request_deadline_seconds=1)), ScriptedModel(stalled)
    )

    assert result.failure is FailureCategory.RESEARCH_LIMIT_REACHED


async def test_failure_saving_research_is_a_failed_call_and_the_other_side_survives(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    If one group's findings cannot be saved the call fails and is not kept as findings.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
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
    scenario.lead_reply = fan_out_then([])
    state = make_state()
    real_save = state.store.save_research

    def save_unless_conservative(conversation_id, brief, findings) -> None:
        """
        Fail only when the saved findings would include the conservative group.
        """
        if any(item.group is SourceGroup.CONSERVATIVE for item in findings):
            raise OSError("storage unavailable")
        real_save(conversation_id, brief, findings)

    state.store.save_research = save_unless_conservative

    result = await run_turn(MESSAGES, state, scenario.model)

    assert result.failure is None
    assert any(
        record.tool == "research_conservative_coverage" and record.outcome == "failure"
        for record in result.tool_calls
    )
    assert state.findings[SourceGroup.CONSERVATIVE] == []


async def test_writer_failure_is_a_recorded_failed_call_and_the_turn_ends_plainly(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    A Writer error is reported to the Lead, and no unwritten answer is invented.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)

    async def writer_down(call: ModelCall):
        """
        Fail every Writer call and script the other agents as usual.
        """
        if "You are the Writer" in call.system_instructions:
            provider_outage(call)
        return await scenario.dispatch(call)

    result = await run_turn(MESSAGES, make_state(), ScriptedModel(writer_down))

    assert result.failure is FailureCategory.INVALID_OUTPUT
    assert any(
        record.tool == "write_answer" and record.outcome == "failure"
        for record in result.tool_calls
    )


def quake_headlines() -> list[ArticleCandidate]:
    """
    Build headlines in which one story is reported by three outlets and one by two.
    """
    day = date(2026, 11, 6)
    return [
        ArticleCandidate(outlet_id=o, url=f"https://{o}.example/{n}", title=t, published_at=day)
        for n, (o, t) in enumerate([
            ("npr", "Powerful earthquake strikes coastal Turkey city"),
            ("fox", "Earthquake strikes Turkey coastal city, dozens dead"),
            ("cbs", "Turkey earthquake: rescuers search coastal city"),
            ("nbc", "Election results announced in Brazil runoff"),
            ("nypost", "Brazil runoff election results announced"),
            ("npr", "Local school board votes on budget"),
        ])
    ]


TURKEY_TOPIC: dict[str, Any] = {"label": "Turkey earthquake response", "headline_numbers": [1, 2, 3]}
BRAZIL_TOPIC: dict[str, Any] = {"label": "Brazil runoff results", "headline_numbers": [4, 5]}
SCHOOL_TOPIC: dict[str, Any] = {"label": "School board budget", "headline_numbers": [6]}


def topic_handler(proposal: Any, search: dict[str, Any] | None = None):
    """
    Build a model script that answers only the two topic-step agents.
    """
    clusterer_inputs: list[str] = []

    def reply(call: ModelCall):
        """
        Plan the search, then cluster the numbered headlines into the given topics.
        """
        if "You are the Topic Planner" in call.system_instructions:
            return FinalOutput(search or {})
        if "You are the Topic Clusterer" in call.system_instructions:
            clusterer_inputs.append(call.input_text)
            topics = proposal(call, len(clusterer_inputs)) if callable(proposal) else proposal
            return FinalOutput({"topics": topics})
        raise AssertionError("Only the topic step may run before a topic is chosen.")

    reply.clusterer_inputs = clusterer_inputs  # type: ignore[attr-defined]
    return reply


def keyword_topics(call: ModelCall, attempt: int = 1) -> list[dict[str, Any]]:
    """
    Group the numbered headlines the clusterer was shown by the story they mention.
    """
    shown: str = call.input_items[0]["content"]
    topics: list[dict[str, Any]] = []
    for keyword, label in (("Turkey", "Turkey earthquake response"), ("Brazil", "Brazil runoff results")):
        numbers = [
            int(line.split(".", 1)[0]) for line in shown.splitlines()
            if line[:1].isdigit() and keyword in line
        ]
        if numbers:
            topics.append({"label": label, "headline_numbers": numbers})
    return topics


def route_headlines(fake_sources, by_query: dict[str, list[ArticleCandidate]]) -> None:
    """
    Make the fake headline source answer each query with its own scripted list.
    """

    def discover(query, start_date, end_date, outlets) -> ArticleSearchResult:
        """Record the call and return the headlines scripted for this query."""
        fake_sources.headline_calls.append(
            {"query": query, "start_date": start_date, "end_date": end_date}
        )
        found = by_query.get(query, [])
        reporting = {candidate.outlet_id for candidate in found}
        return ArticleSearchResult(
            candidates=tuple(found),
            outcomes=tuple(
                SourceAccessOutcome(
                    outlet_id=outlet, status="success" if outlet in reporting else "no_results",
                )
                for outlet in outlets
            ),
        )

    fake_sources.discover_headlines = discover


async def test_first_message_proposes_clustered_topics_before_any_research(
    make_state,
    fake_sources,
) -> None:
    """
    A new request gets neutral topic choices built from headlines, never article headlines.
    """
    fake_sources.headlines = quake_headlines()
    model = ScriptedModel(topic_handler([TURKEY_TOPIC, BRAZIL_TOPIC, SCHOOL_TOPIC]))

    result = await run_turn(
        [ChatMessage(role="user", content="What is happening in the news?")],
        make_state(), model, today=date(2026, 11, 7),
    )

    assert result.failure is None
    assert result.answer.startswith("Which of these topics would you like compared?")
    assert result.answer.count("](#compare-event=") == 2
    assert "[Turkey earthquake response](" in result.answer
    assert "outlets" not in unquote(result.answer).replace("different outlets", "")
    assert "Nov 6" not in result.answer
    assert "Powerful earthquake strikes" not in result.answer
    assert "School board" not in result.answer
    assert "from 2026-10-07 to 2026-11-07" in unquote(result.answer)
    assert [record.tool for record in result.tool_calls] == ["search_recent_events", "group_topics"]
    assert not fake_sources.search_calls
    assert all("You are the Topic" in call.system_instructions for call in model.calls)


async def test_the_planner_extracts_the_subject_and_period_for_the_headline_search(
    make_state,
    fake_sources,
) -> None:
    """
    The subject words and any stated dates drive the headline search.
    """
    fake_sources.headlines = quake_headlines()
    search = {"topic": "Turkey", "start_date": "2026-05-11", "end_date": "2026-11-11"}
    model = ScriptedModel(topic_handler([TURKEY_TOPIC, BRAZIL_TOPIC], search))

    await run_turn(
        [ChatMessage(role="user", content="Tell me about Turkey over the last 6 months")],
        make_state(), model, today=date(2026, 11, 11),
    )

    assert fake_sources.headline_calls[0] == {
        "query": "Turkey", "start_date": date(2026, 5, 11), "end_date": date(2026, 11, 11),
    }


async def test_a_topic_that_cites_a_headline_that_does_not_exist_is_sent_back_once(
    make_state,
    fake_sources,
) -> None:
    """
    An invented headline number never reaches the reader; the clusterer is corrected once.
    """
    fake_sources.headlines = quake_headlines()
    invented = {"label": "Made up story", "headline_numbers": [1, 99]}
    handler = topic_handler(
        lambda call, attempt: [invented] if attempt == 1 else [TURKEY_TOPIC, BRAZIL_TOPIC],
    )
    model = ScriptedModel(handler)

    result = await run_turn(
        [ChatMessage(role="user", content="What is happening?")], make_state(), model,
    )

    assert len(handler.clusterer_inputs) == 2
    assert "Made up story" not in result.answer
    assert "Turkey earthquake response" in result.answer


async def test_no_matches_are_stated_and_the_closest_related_topics_are_offered(
    make_state,
    fake_sources,
) -> None:
    """
    A request with no matching headlines says so and proposes related topics.
    """
    route_headlines(fake_sources, {"": quake_headlines()})
    model = ScriptedModel(topic_handler(keyword_topics, {"topic": "Brazil runoff elections"}))

    result = await run_turn(
        [ChatMessage(role="user", content="Tell me about Mars")], make_state(), model,
    )

    assert result.answer.startswith("No matches found for “Brazil runoff elections”.")
    assert "closest related topics" in result.answer
    assert result.answer.index("Brazil runoff results") < result.answer.index("Turkey earthquake")
    assert [call["query"] for call in fake_sources.headline_calls] == ["Brazil runoff elections", ""]


async def test_one_matching_topic_is_shown_first_and_related_topics_fill_the_list(
    make_state,
    fake_sources,
) -> None:
    """
    With a single match, related topics are added so the reader has at least two choices.
    """
    turkey_only = [c for c in quake_headlines() if "Turkey" in c.title]
    route_headlines(fake_sources, {"Turkey": turkey_only, "": quake_headlines()})

    model = ScriptedModel(topic_handler(keyword_topics, {"topic": "Turkey"}))

    result = await run_turn(
        [ChatMessage(role="user", content="Turkey news")], make_state(), model,
    )

    assert result.answer.startswith("I found one matching topic, plus related ones:")
    assert result.answer.index("Turkey earthquake response") < result.answer.index("Brazil runoff results")
    assert result.answer.count("](#compare-event=") == 2


async def test_nothing_found_anywhere_says_no_matches_without_inventing_topics(
    make_state,
    fake_sources,
) -> None:
    """
    When no headlines exist at all, the reply states that and asks for a broader search.
    """
    model = ScriptedModel(topic_handler([]))

    result = await run_turn(
        [ChatMessage(role="user", content="Tell me about Mars")], make_state(), model,
    )

    assert result.answer.startswith("No matches found")
    assert "broader" in result.answer
    assert "](#compare-event=" not in result.answer


async def test_headline_search_failure_is_recorded_and_offers_nothing(
    make_state,
    fake_sources,
) -> None:
    """
    A source crash fails the call and the reader is not shown topics from nowhere.
    """
    def crash(*args: object) -> None:
        """
        Fail like a broken source layer.
        """
        raise RuntimeError("feed parser crashed")

    fake_sources.discover_headlines = crash
    handler = topic_handler([TURKEY_TOPIC])
    result = await run_turn(
        [ChatMessage(role="user", content="What is happening?")], make_state(), ScriptedModel(handler),
    )

    assert result.answer == "Recent headlines could not be loaded. Please try again shortly."
    assert any(r.tool == "search_recent_events" and r.outcome == "failure" for r in result.tool_calls)
    assert handler.clusterer_inputs == []


async def test_a_typed_message_after_the_options_starts_the_topic_step_again(
    make_state,
    fake_sources,
) -> None:
    """
    Only clicking a topic starts research; typing again proposes fresh topics.
    """
    fake_sources.headlines = quake_headlines()
    handler = topic_handler([TURKEY_TOPIC, BRAZIL_TOPIC])
    model = ScriptedModel(handler)
    first = await run_turn(
        [ChatMessage(role="user", content="What is happening?")], make_state(), model,
    )

    second = await run_turn(
        [
            ChatMessage(role="user", content="What is happening?"),
            ChatMessage(role="assistant", content=first.answer),
            ChatMessage(role="user", content="Something about Brazil"),
        ],
        make_state(), model,
    )

    assert len(handler.clusterer_inputs) == 2
    assert second.answer.startswith("Which of these topics")


async def test_a_selected_topic_skips_the_topic_step_and_goes_to_research(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    Clicking a proposed topic starts the usual two-group research, with no second topic step.
    """
    fake_sources.headlines = quake_headlines()
    topics = await run_turn(
        [ChatMessage(role="user", content="What is happening?")],
        make_state(), ScriptedModel(topic_handler([TURKEY_TOPIC, BRAZIL_TOPIC])),
        today=date(2026, 11, 7),
    )
    selection: str = topics.answer.split("](#", 1)[1].split(")", 1)[0]
    question: str = parse_qs(selection)["compare-event"][0]
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    lead = scenario.lead_reply

    def research_selected_topic(call: ModelCall):
        """Check the Lead was given the chosen topic, then follow the normal script."""
        if not call.tool_results:
            assert "Turkey earthquake response" in call.input_text
        return lead(call)

    scenario.lead_reply = research_selected_topic
    calls_before = len(fake_sources.headline_calls)

    result = await run_turn(
        [ChatMessage(role="user", content=question)], make_state(), scenario.model,
    )

    assert result.failure is None
    assert "| Aspect | Liberal outlets | Conservative outlets |" in result.answer
    assert len(fake_sources.headline_calls) == calls_before
    assert not any("You are the Topic" in call.system_instructions for call in scenario.model.calls)


async def test_a_chosen_six_month_topic_keeps_its_full_period_through_research(
    make_state, fake_sources, articles,
) -> None:
    """
    The period carried by a chosen topic is the period both groups research.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    research = scenario.lead_reply
    window_args: dict[str, str | None] = {
        "event": "Paris riots", "start_date": "2026-05-11", "end_date": "2026-11-11",
        "focus_question": None,
    }

    def reply(call: ModelCall) -> ToolCalls | FinalOutput:
        """Research the chosen topic for its stated months, write, then finish."""
        if not call.tool_results:
            return ToolCalls([
                ("research_liberal_coverage", window_args),
                ("research_conservative_coverage", window_args),
            ])
        if len(call.tool_results) == 2:
            return research(call)
        return FinalOutput({"brief": {
            "status": "clear", "event": "Paris riots",
            "start_date": "2026-05-11", "end_date": "2026-11-11",
        }})

    scenario.lead_reply = reply
    result = await run_turn(
        [ChatMessage(
            role="user",
            content="How did different outlets cover “Paris riots” from 2026-05-11 to 2026-11-11?",
        )],
        make_state(), scenario.model, today=date(2026, 11, 11),
    )

    assert result.failure is None
    assert "| Aspect | Liberal outlets | Conservative outlets |" in result.answer
    assert not fake_sources.headline_calls
    assert len(fake_sources.search_calls) == 2
    assert all(
        (call["start_date"], call["end_date"]) == (date(2026, 5, 11), date(2026, 11, 11))
        for call in fake_sources.search_calls
    )


def detailed_report(liberal_article, conservative_article) -> dict[str, Any]:
    """
    Build a Writer report with the extra sections of a detailed report.
    """
    report = writer_report(liberal_article, conservative_article)
    report["accounts"] = [{
        "text": "A police spokesperson said officers responded to violence.",
        "passage_ids": [conservative_article.passages[0].passage_id],
    }]
    report["discrepancies"] = [{
        "text": "The outlets gave different crowd estimates.",
        "passage_ids": [liberal_article.passages[1].passage_id],
    }]
    report["timeline"] = [{
        "text": "The protests began on Saturday.",
        "passage_ids": [liberal_article.passages[0].passage_id],
    }]
    return report


def write_detailed_from_saved_research(articles):
    """
    Build a Lead script that writes a detailed report with no new research.
    """
    alignment = alignment_for(articles["npr"], articles["fox"])

    def reply(call: ModelCall):
        """
        Write once with detailed=true, then finish.
        """
        if not call.tool_results:
            return ToolCalls([("write_answer", {
                "question": "Give me a detailed report.", "alignment": alignment, "detailed": True,
            })])
        return FinalOutput(lead_outcome())

    return reply


async def test_detailed_followup_expands_the_previous_briefing(
    make_state,
    fake_sources,
    articles: dict[str, ArticleRecord],
) -> None:
    """A follow-up compares exact excerpts and avoids repeating the briefing."""
    quote: str = "officers blocked the eastern bridge"
    npr: ArticleRecord = articles["npr"]
    fox: ArticleRecord = articles["fox"]
    passage_id: str = npr.passages[0].passage_id
    fox_passage_id: str = fox.passages[0].passage_id
    articles["npr"] = npr.model_copy(update={"passages": (
        npr.passages[0].model_copy(update={"text": f"Witnesses said {quote}."}),
        *npr.passages[1:],
    )})
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    first = await run_turn(MESSAGES, make_state(), scenario.model)
    searches_before = len(fake_sources.search_calls)
    scenario.lead_reply = write_detailed_from_saved_research(articles)
    analysis: dict[str, Any] = {
        "text": "NPR describes how the police response affected protesters' routes.",
        "passage_ids": [passage_id],
        "quotes": [{"text": quote, "passage_id": passage_id}],
    }
    repeated_claim: dict[str, Any] = {
        "text": "Large protests took place in Paris.",
        "passage_ids": [passage_id],
    }
    report: dict[str, Any] = {
        "summary": [repeated_claim, analysis],
        "overlap": [repeated_claim, {
            "text": "Both outlets describe the police response near the bridge.",
            "passage_ids": [passage_id, fox_passage_id],
        }],
        "differences": [{
            "text": "NPR traces road closures, while Fox focuses on arrests.",
            "passage_ids": [passage_id, fox_passage_id],
        }],
        "accounts": [{
            "text": "NPR attributes the bridge closure to witnesses at the scene.",
            "passage_ids": [passage_id],
        }],
    }
    altered_analysis: dict[str, Any] = analysis | {
        "quotes": [{"text": "officers blocked the western bridge", "passage_id": passage_id}],
    }
    scenario.writer_replies = [
        writer_report(npr, fox),
        report | {"summary": [altered_analysis]},
        report,
    ]

    followup: list[ChatMessage] = [
        *MESSAGES,
        ChatMessage(role="assistant", content=first.answer),
        ChatMessage(role="user", content="Give me a detailed report with sources."),
    ]
    second = await run_turn(followup, make_state(), scenario.model)

    assert second.failure is None
    prose, sources = second.answer.split("\n\n## Sources\n")
    assert f"“{quote}” [1]" in prose
    assert "western bridge" not in second.answer
    assert "Large protests took place in Paris." not in prose
    assert "| Aspect |" not in prose
    assert "## Where coverage overlaps\n- Both outlets describe" in prose
    assert "## Where coverage differs\n- NPR traces road closures" in prose
    assert "## Attributed accounts\n- NPR attributes" in prose
    assert "## Limitations" not in second.answer
    assert npr.canonical_url in sources and fox.canonical_url in sources
    assert len(fake_sources.search_calls) == searches_before
    assert len(scenario.writer_calls) == 3
    writer_input: str = scenario.writer_calls[1].input_items[0]["content"]
    assert "Report type: follow-up" in writer_input
    assert json.dumps(first.answer) in writer_input


async def test_a_briefing_cannot_carry_detailed_sections(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    The Writer is corrected once when a briefing includes detailed-only sections.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    scenario.writer_replies = [
        detailed_report(articles["npr"], articles["fox"]),
        writer_report(articles["npr"], articles["fox"]),
    ]

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    assert result.failure is None
    assert len(scenario.writer_calls) == 2
    assert "## Timeline" not in result.answer


async def test_a_clusterer_that_returns_nothing_still_leaves_the_reader_with_topics(
    make_state,
    fake_sources,
) -> None:
    """
    If the model groups nothing usable, headline word overlap supplies the choices.
    """
    fake_sources.headlines = quake_headlines()
    model = ScriptedModel(topic_handler([]))

    result = await run_turn(
        [ChatMessage(role="user", content="What is happening?")], make_state(), model,
    )

    assert result.failure is None
    assert result.answer.count("](#compare-event=") == 2
    assert "No matches found" not in result.answer


async def test_a_whole_headline_as_the_request_still_proposes_related_topics(
    make_state,
    fake_sources,
) -> None:
    """
    A search that matches nothing falls back to the closest topics rather than a dead end.
    """
    route_headlines(fake_sources, {"": quake_headlines()})
    search = {"topic": "Brazil president surprise decree overturns runoff election results"}
    model = ScriptedModel(topic_handler(keyword_topics, search))

    result = await run_turn(
        [ChatMessage(role="user", content="Tell me about that Brazil decree headline")],
        make_state(), model,
    )

    assert result.answer.startswith("No matches found for")
    assert result.answer.count("](#compare-event=") == 2
    assert result.answer.index("Brazil runoff results") < result.answer.index("Turkey earthquake")


async def test_a_new_comparison_cannot_be_written_without_aspects(
    make_state,
    fake_sources,
    articles,
) -> None:
    """
    An empty alignment is sent back so a chosen topic always yields both sides' bullets.
    """
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    good = alignment_for(articles["npr"], articles["fox"])
    sequence = [[], good]

    def reply(call: ModelCall):
        """Write with no aspects first, then with a real alignment."""
        done = len(call.tool_results)
        if done == 0:
            return fan_out_then(good)(call)
        if done in (2, 3):
            return ToolCalls([("write_answer", {"question": "q", "alignment": sequence[done - 2]})])
        return FinalOutput(lead_outcome())

    scenario.lead_reply = reply

    result = await run_turn(MESSAGES, make_state(), scenario.model)

    writes = [r for r in result.tool_calls if r.tool == "write_answer"]
    assert [record.outcome for record in writes] == ["failure", "success"]
    assert "at least one aspect" in writes[0].error
    assert len(scenario.writer_calls) == 1
    assert "| Aspect | Liberal outlets | Conservative outlets |" in result.answer
