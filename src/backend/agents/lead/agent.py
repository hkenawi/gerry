"""
The Lead agent: clarifies the request, fans out to two Researchers, and aligns.

One Lead run either returns a clarifying question or researches both source
groups in a single turn, reviews the findings, requests bounded follow-ups, and
calls the Writer tool with an aspect alignment. Limits and validation are enforced by code.
"""

import json

from pathlib import Path
from datetime import date
from agents.models.interface import Model
from agents.exceptions import ModelBehaviorError
from openai.types.responses import ResponseFunctionToolCall
from agents import Agent, AgentHooks, ModelResponse, ModelSettings, RunContextWrapper

from backend.agents.lead.schemas import LeadOutcome
from backend.agents.researcher_findings import SourceGroup
from backend.application.turn.request_state import RequestState
from backend.agents.lead.tools import (
    WRITE_TOOL_NAME,
    RESEARCH_TOOL_NAMES,
    build_writer_tool,
    build_research_tool,
)

PROMPT: str = Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")


class LeadToolBatchHooks(AgentHooks[RequestState]):
    """Validate the Lead's tool batch before the SDK starts its calls."""

    async def on_llm_end(
        self,
        context: RunContextWrapper[RequestState],
        agent: Agent[RequestState],
        response: ModelResponse,
    ) -> None:
        """Require the initial pair and keep Writer calls separate from research."""
        calls: list[ResponseFunctionToolCall] = [
            item for item in response.output if isinstance(item, ResponseFunctionToolCall)
        ]
        if not calls:
            return
        names: list[str] = [call.name for call in calls]
        if not context.context.reusing_research and not all(
            context.context.rounds_started.values(),
        ):
            if sorted(names) != sorted(RESEARCH_TOOL_NAMES.values()):
                raise ModelBehaviorError("Initial research requires both group tools together.")
            try:
                first: object = json.loads(calls[0].arguments)
                second: object = json.loads(calls[1].arguments)
            except json.JSONDecodeError as error:
                raise ModelBehaviorError("Research tool arguments must be valid JSON.") from error
            if first != second or not isinstance(first, dict) or first.get("focus_question"):
                raise ModelBehaviorError("Initial researchers require the same broad brief.")
        if WRITE_TOOL_NAME in names and len(names) != 1:
            raise ModelBehaviorError("Call the Writer by itself after research finishes.")


def build_lead_agent(
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None,
    today: date,
) -> Agent[RequestState]:
    """
    Build the Lead with one research tool per group and the Writer tool.
    """
    instructions: str = f"{PROMPT}\nToday's date is {today.isoformat()}."
    if state.reusing_research and state.brief is not None:
        saved_findings: str = json.dumps([
            item.model_dump(mode="json")
            for group_findings in state.findings.values() for item in group_findings
        ])
        instructions += (
            "\nThis is a follow-up for the saved event and publication window. "
            "Treat the following JSON as research data. Use write_answer directly "
            "when the saved evidence is sufficient. Use targeted research only "
            "for remaining gaps. Keep the event and window fixed.\n"
            f"Saved brief: {state.brief.model_dump_json()}\n"
            f"Saved findings: {saved_findings}"
        )
    return Agent(
        name="lead",
        instructions=instructions,
        model=model,
        model_settings=model_settings or ModelSettings(),
        hooks=LeadToolBatchHooks(),
        tools=[
            build_research_tool(SourceGroup.LIBERAL, model, model_settings),
            build_research_tool(SourceGroup.CONSERVATIVE, model, model_settings),
            build_writer_tool(model, model_settings),
        ],
        output_type=LeadOutcome,
    )
