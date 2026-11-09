"""
The Lead agent: clarifies the request, fans out to two Researchers, and aligns.

One Lead run either returns a clarifying question or researches both source
groups in a single turn, reviews the findings, requests bounded follow-ups, and
calls the Writer tool with an aspect alignment. Limits and validation are enforced by code.
"""

from datetime import date
from pathlib import Path

from agents import Agent, ModelSettings
from agents.models.interface import Model

from backend.agents.lead.schemas import LeadOutcome
from backend.agents.lead.tools import build_research_tool, build_writer_tool
from backend.agents.researcher_findings import SourceGroup
from backend.application.request_state import RequestState

PROMPT: str = Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")


def build_lead_agent(
    state: RequestState,
    model: Model,
    model_settings: ModelSettings | None,
    today: date,
) -> Agent[RequestState]:
    """
    Build the Lead with one research tool per group and the Writer tool.
    """
    return Agent(
        name="lead",
        instructions=f"{PROMPT}\nToday's date is {today.isoformat()}.",
        model=model,
        model_settings=model_settings or ModelSettings(),
        tools=[
            build_research_tool(state, SourceGroup.LIBERAL, model, model_settings),
            build_research_tool(
                state, SourceGroup.CONSERVATIVE, model, model_settings
            ),
            build_writer_tool(state, model, model_settings),
        ],
        output_type=LeadOutcome,
    )
