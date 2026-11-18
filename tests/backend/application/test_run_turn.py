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
from uuid import UUID
from datetime import date, timedelta
from openai import APIConnectionError
from collections.abc import Callable
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
    Handler,
    ModelCall,
    ScriptedModel,
    ToolCalls,
)
from backend.application.turn.failure_category import FailureCategory, describe_failure

WINDOW_ARGS: dict[str, Any] = {
    "event": "Paris protests",
    "focus_question": None,
}
MESSAGES: list[ChatMessage] = [
    ChatMessage(
        role="user",
        content="How did different outlets cover “Paris protests”?",
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
            "start_date": date.min.isoformat(),
            "end_date": date.today().isoformat(),
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
    state = make_state()

    result = await run_turn(MESSAGES, state, scenario.model)

    assert result.failure is None
    body, sources = result.answer.split("\n\n## Sources\n")
    assert body.startswith("Large protests took place in Paris. [1]\n\n")
    assert body.index("## Where coverage differs") < body.index("## Coverage aspects")
    assert "The conservative outlets stressed property damage. [2]" in body
    assert "### Police response" in body
    assert "**Liberal coverage:** Main focus at NPR online news" in body
    assert "**Conservative coverage:** Main focus at Fox News Digital" in body
    assert "| Aspect |" not in body
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
    assert "## Coverage aspects" in result.answer
    assert "No usable articles for this sample." in result.answer
    assert "Choose another issue from the front page" in result.answer
    assert "*Sample:" in result.answer


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


async def test_event_is_fixed_after_the_first_research_call(
    make_state,
) -> None:
    """
    A later call cannot change the subject of the comparison.
    """
    state = make_state()

    first, problem = check_brief(state, "Paris protests")
    second, second_problem = check_brief(state, "London protests")

    assert problem is None and first is not None
    assert second is None
    assert "fixed" in second_problem


def test_research_includes_older_feed_entries_and_preserves_scope_on_followup(make_state) -> None:
    """Use the full feed and keep the original upper bound during follow-ups."""
    state = make_state()
    first, problem = check_brief(state, "Paris protests", today=date(2026, 11, 11))
    followup, followup_problem = check_brief(
        state, "Paris protests", today=date(2026, 11, 12),
    )

    assert problem is None and followup_problem is None
    assert first == followup == (date.min, date(2026, 11, 11))


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
    assert "## Coverage aspects" in result.answer
    assert "| Aspect |" not in result.answer


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
    assert "## Coverage aspects" in result.answer


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


def topic_handler(
    proposal: list[dict[str, Any]] | Callable[[str, int], list[dict[str, Any]]],
    search: dict[str, Any] | None = None,
) -> Handler:
    """Script one topic agent that calls the headline tool and groups its results."""
    attempts: int = 0

    def reply(call: ModelCall) -> ToolCalls | FinalOutput:
        """Use search results or the headlines provided for the broader pass."""
        nonlocal attempts
        assert "You are the Topic Discovery agent" in call.system_instructions
        if "search_recent_events" in call.tool_names:
            return ToolCalls([("search_recent_events", search or {})])
        shown: str = (
            call.tool_results[-1] if call.tool_results else call.input_items[0]["content"]
        )
        attempts += 1
        topics: list[dict[str, Any]] = proposal(shown, attempts) if callable(proposal) else proposal
        return FinalOutput({"topics": topics})

    return reply


def keyword_topics(shown: str, attempt: int = 1) -> list[dict[str, Any]]:
    """Group the numbered headlines by the story they mention."""
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
    assert "How did different outlets cover “Turkey earthquake response”?" in unquote(
        result.answer,
    )
    assert [(record.agent, record.tool) for record in result.tool_calls] == [
        ("topic_discovery", "search_recent_events"),
        ("topic_discovery", "group_topics"),
    ]
    assert not fake_sources.search_calls
    assert len({call.system_instructions for call in model.calls}) == 1
    assert "search_recent_events" in model.calls[0].tool_names


async def test_discovery_searches_current_feeds_when_the_reader_requests_dates(
    make_state,
    fake_sources,
) -> None:
    """
    A date request leaves the feed unrestricted and gets a scope note in the answer.
    """
    fake_sources.headlines = quake_headlines()
    search: dict[str, str | bool] = {"topic": "Turkey", "date_filter_requested": True}
    model = ScriptedModel(topic_handler([TURKEY_TOPIC, BRAZIL_TOPIC], search))

    result = await run_turn(
        [ChatMessage(role="user", content="Tell me about Turkey over the last 6 months")],
        make_state(), model, today=date(2026, 11, 11),
    )

    assert fake_sources.headline_calls[0] == {
        "query": "Turkey", "start_date": date.min, "end_date": date(2026, 11, 11),
    }
    assert "only searches current publisher feeds" in result.answer
    assert "Turkey earthquake response" in result.answer


async def test_a_topic_that_cites_a_headline_that_does_not_exist_is_sent_back_once(
    make_state,
    fake_sources,
) -> None:
    """
    An invented headline number is corrected without fetching the headlines again.
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

    assert len(fake_sources.headline_calls) == 1
    assert "Made up story" not in result.answer
    assert "Turkey earthquake response" in result.answer


async def test_subject_miss_offers_three_topics_ranked_by_distinct_publishers(
    make_state,
    fake_sources,
) -> None:
    """
    A subject miss offers the three most widely reported stories in the feeds.
    """
    headlines: list[ArticleCandidate] = quake_headlines()
    for title, outlets in (
        ("Coastal flooding prompts evacuations", ("npr", "fox", "cbs", "nbc")),
        ("Rugby championship tournament begins", ("npr", "fox")),
    ):
        for outlet in outlets:
            headlines.append(ArticleCandidate(
                outlet_id=outlet,
                url=f"https://{outlet}.example/{len(headlines)}",
                title=title,
                published_at=date(2026, 11, 5),
            ))
    route_headlines(fake_sources, {"": headlines})
    model = ScriptedModel(topic_handler(keyword_topics, {"topic": "Brazil runoff elections"}))

    result = await run_turn(
        [ChatMessage(role="user", content="Tell me about the Brazil runoff")], make_state(), model,
    )

    assert result.answer.startswith("No comparison topics found for “Brazil runoff elections”")
    assert (
        "Take a look at the most-covered topics from the current feeds "
        "and choose one you’re interested in:"
    ) in result.answer
    assert result.answer.count("](#compare-event=") == 3
    assert (
        result.answer.index("[Coastal flooding")
        < result.answer.index("[Powerful earthquake")
        < result.answer.index("[Election results")
    )
    assert "Rugby championship" not in result.answer
    assert [call["query"] for call in fake_sources.headline_calls] == ["Brazil runoff elections", ""]


async def test_one_matching_topic_is_enough_to_skip_the_fallback(
    make_state,
    fake_sources,
) -> None:
    """
    A single matching comparison is shown without filling the list with other stories.
    """
    turkey_only = [c for c in quake_headlines() if "Turkey" in c.title]
    route_headlines(fake_sources, {"Turkey": turkey_only, "": quake_headlines()})

    model = ScriptedModel(topic_handler(keyword_topics, {"topic": "Turkey"}))

    result = await run_turn(
        [ChatMessage(role="user", content="Turkey news")], make_state(), model,
    )

    assert "Turkey earthquake response" in result.answer
    assert result.answer.count("](#compare-event=") == 1
    assert [call["query"] for call in fake_sources.headline_calls] == ["Turkey"]


async def test_nothing_found_anywhere_says_no_matches_without_inventing_topics(
    make_state,
    fake_sources,
) -> None:
    """
    When no headlines exist at all, the reply states that without inventing topics.
    """
    model = ScriptedModel(topic_handler([]))

    result = await run_turn(
        [ChatMessage(role="user", content="Tell me about Mars")], make_state(), model,
    )

    assert result.answer == "No comparison topics found in the current feeds."
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
    model = ScriptedModel(topic_handler([TURKEY_TOPIC]))
    result = await run_turn(
        [ChatMessage(role="user", content="What is happening?")], make_state(), model,
    )

    assert result.answer == "Recent headlines could not be loaded. Please try again shortly."
    assert [(record.agent, record.tool, record.outcome) for record in result.tool_calls] == [
        ("topic_discovery", "search_recent_events", "failure"),
    ]
    assert len(model.calls) == 1


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

    assert len(fake_sources.headline_calls) == 2
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
    assert "## Coverage aspects" in result.answer
    assert len(fake_sources.headline_calls) == calls_before
    assert not any("You are the Topic" in call.system_instructions for call in scenario.model.calls)


async def test_dated_comparison_text_runs_current_feed_discovery(
    make_state,
    fake_sources,
) -> None:
    """A typed date range cannot bypass the current-feed topic step."""
    fake_sources.headlines = quake_headlines()
    model: ScriptedModel = ScriptedModel(topic_handler(
        keyword_topics, {"topic": "Turkey", "date_filter_requested": True},
    ))

    result = await run_turn(
        [ChatMessage(
            role="user",
            content="How did different outlets cover “Turkey” from 2026-05-11 to 2026-11-11?",
        )],
        make_state(),
        model,
        today=date(2026, 11, 17),
    )

    assert result.failure is None
    assert "only searches current publisher feeds" in result.answer
    assert "Turkey earthquake response" in result.answer
    assert fake_sources.headline_calls == [{
        "query": "Turkey", "start_date": date.min, "end_date": date(2026, 11, 17),
    }]
    assert fake_sources.search_calls == []


@pytest.mark.parametrize("resolution", ["ready", "broaden"])
async def test_issue_research_uses_the_same_scoped_feed_snapshot(
    make_state,
    fake_sources,
    articles: dict[str, ArticleRecord],
    resolution: str,
) -> None:
    """A typed or selected issue keeps alternate headlines and excludes unrelated ones."""
    scenario: Scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    selected: list[ArticleCandidate] = [
        ArticleCandidate(
            outlet_id=outlet,
            url=f"https://{outlet}.example/a",
            title=title,
            published_at=date(2026, 11, 5),
        )
        for outlet, title in (
            ("npr", "Demonstrators gather in Paris"),
            ("nbc", "Paris demonstrations draw crowds"),
            ("fox", "French authorities respond to unrest"),
            ("nypost", "Police react as protesters gather in the capital"),
        )
    ]
    fake_sources.headlines = [*selected, ArticleCandidate(
        outlet_id="npr",
        url="https://npr.example/roundup",
        title="Paris protests and Nvidia leadership in today's roundup",
        published_at=date(2026, 11, 5),
    )]

    async def reply(call: ModelCall) -> ToolCalls | FinalOutput:
        """Resolve a bounded issue, then run the normal research and writing flow."""
        if "You are the Topic Discovery agent" in call.system_instructions:
            if not call.tool_results:
                return ToolCalls([("search_recent_events", {})])
            return FinalOutput({
                "resolution": resolution,
                "topics": [{
                    "label": "Paris protests",
                    "description": "Demonstrations in Paris and the response to them.",
                    "headline_numbers": [1, 2, 3, 4],
                }],
            })
        return await scenario.dispatch(call)

    question: str = (
        "Compare coverage of the Paris protests" if resolution == "ready"
        else "Police react as protesters gather in the capital"
    )
    model: ScriptedModel = ScriptedModel(reply)
    result = await run_turn([ChatMessage(role="user", content=question)], make_state(), model)
    if resolution == "broaden":
        assert "broader issue" in result.answer
        selection: str = result.answer.split("](#", 1)[1].split(")", 1)[0]
        params: dict[str, list[str]] = parse_qs(selection)
        result = await run_turn(
            [ChatMessage(role="user", content=params["compare-event"][0])],
            make_state(),
            model,
            issue_id=UUID(params["issue"][0]),
        )

    assert result.failure is None
    assert "## Coverage aspects" in result.answer
    assert fake_sources.search_calls == []
    scoped_urls: set[str] = {
        candidate["url"]
        for record in result.tool_calls if record.tool == "search_articles" and record.result
        for candidate in json.loads(record.result)["candidates"]
    }
    assert scoped_urls == {candidate.url for candidate in selected}
    assignments: list[ModelCall] = [
        call for call in model.calls
        if "You are a Researcher" in call.system_instructions and not call.tool_results
    ]
    assert len(assignments) == 2
    assert all("Demonstrations in Paris and the response to them." in call.input_text
               for call in assignments)


def detailed_report(liberal_article, conservative_article) -> dict[str, Any]:
    """
    Build a Writer report with the extra sections of a detailed report.
    """
    report = writer_report(liberal_article, conservative_article)
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


async def test_explicit_request_gets_the_full_report_with_excerpts_in_sources(
    make_state,
    fake_sources,
    articles: dict[str, ArticleRecord],
) -> None:
    """An explicit full report includes the comparison and keeps excerpts in Sources."""
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
    assert quote not in prose
    assert f"> {quote}" in sources
    assert "western bridge" not in second.answer
    assert prose.count("Large protests took place in Paris.") == 1
    assert "## Coverage aspects" in prose
    assert "## Where coverage overlaps" in prose
    assert "## Where coverage differs" in prose
    assert "## Attributed accounts" not in prose
    assert "## Limitations" not in second.answer
    assert npr.canonical_url in sources and fox.canonical_url in sources
    assert len(fake_sources.search_calls) == searches_before
    assert len(scenario.writer_calls) == 3
    writer_input: str = scenario.writer_calls[1].input_items[0]["content"]
    assert "Report type: detailed" in writer_input
    assert json.dumps(first.answer) in writer_input


@pytest.mark.parametrize("detailed", [False, True])
async def test_a_targeted_followup_does_not_render_a_report(
    make_state,
    fake_sources,
    articles: dict[str, ArticleRecord],
    detailed: bool,
) -> None:
    """A question about one fact returns only the answer and its sources."""
    scenario = Scenario()
    wire_full_scenario(scenario, fake_sources, articles)
    first = await run_turn(MESSAGES, make_state(), scenario.model)
    def reply(call: ModelCall) -> ToolCalls | FinalOutput:
        """Ask the Writer to answer and let the app decide which layout applies."""
        if not call.tool_results:
            return ToolCalls([("write_answer", {
                "question": "Give me a detailed report.", "alignment": [], "detailed": detailed,
            })])
        return FinalOutput(lead_outcome())

    scenario.lead_reply = reply
    passage_id: str = articles["npr"].passages[0].passage_id
    scenario.writer_replies.append({
        "summary": [{"text": "NPR reported road closures.", "passage_ids": [passage_id]}],
        "overlap": [{"text": "Both articles covered the protests.", "passage_ids": [passage_id]}],
    })

    second = await run_turn([
        *MESSAGES,
        ChatMessage(role="assistant", content=first.answer),
        ChatMessage(role="user", content="What did NPR report about the roads? Include sources."),
    ], make_state(), scenario.model)

    assert second.failure is None
    prose, sources = second.answer.split("\n\n## Sources\n")
    assert prose == "NPR reported road closures. [1]"
    assert articles["npr"].canonical_url in sources
    assert "Reader's question: What did NPR report about the roads?" in (
        scenario.writer_calls[-1].input_text
    )


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


async def test_an_empty_discovery_proposal_still_leaves_the_reader_with_topics(
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


async def test_a_whole_headline_without_matches_gets_the_available_fallback_topics(
    make_state,
    fake_sources,
) -> None:
    """
    A miss lists the available widely covered stories even if there are fewer than three.
    """
    route_headlines(fake_sources, {"": quake_headlines()})
    search = {"topic": "Brazil president surprise decree overturns runoff election results"}
    model = ScriptedModel(topic_handler(keyword_topics, search))

    result = await run_turn(
        [ChatMessage(role="user", content="Tell me about that Brazil decree headline")],
        make_state(), model,
    )

    assert result.answer.startswith("No comparison topics found for")
    assert result.answer.count("](#compare-event=") == 2
    assert result.answer.index("[Powerful earthquake") < result.answer.index("[Election results")


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
    assert "## Coverage aspects" in result.answer
