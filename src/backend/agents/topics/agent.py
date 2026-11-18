"""Build the agent that finds and groups recent headlines before Lead research.

The application supplies the search tool and validates headline references in
the agent's structured output. An empty search can finish without a second
model call."""

from enum import StrEnum
from pathlib import Path
from datetime import date
from dataclasses import dataclass, replace
from agents.models.interface import Model
from agents import (
    Agent,
    FunctionTool,
    ModelSettings,
    RunContextWrapper,
    FunctionToolResult,
    ToolsToFinalOutputResult,
)

from backend.agents.topics.schemas import TopicProposal
from backend.application.turn.request_state import RequestState

DISCOVERY_PROMPT: str = Path(__file__).with_name("discovery_prompt.md").read_text(
    encoding="utf-8",
)
TOPIC_AGENT_MAX_TURNS: int = 3


class TopicActivity(StrEnum):
    """Identify topic discovery in agent runs, tools, and chat logs."""

    AGENT = "topic_discovery"
    SEARCH = "search_recent_events"
    GROUP = "group_topics"


@dataclass(frozen=True)
class TopicAgentConstants:
    """Expose the names shared by the agent and application logging."""

    activity: type[TopicActivity] = TopicActivity


TOPIC_AGENT_CONSTANTS: TopicAgentConstants = TopicAgentConstants()


def _finish_without_headlines(
    _context: RunContextWrapper[RequestState],
    results: list[FunctionToolResult],
) -> ToolsToFinalOutputResult:
    """Return an empty proposal when the search tool has no headlines to group."""
    if any(result.output == "" for result in results):
        return ToolsToFinalOutputResult(is_final_output=True, final_output=TopicProposal())
    return ToolsToFinalOutputResult(is_final_output=False)


def build_topic_discovery_agent(
    model: Model,
    model_settings: ModelSettings | None,
    today: date,
    search_tool: FunctionTool | None = None,
) -> Agent[RequestState]:
    """Build one agent that searches approved headlines and proposes neutral topics."""
    return Agent(
        name=TOPIC_AGENT_CONSTANTS.activity.AGENT.value,
        instructions=f"{DISCOVERY_PROMPT}\nToday's date is {today.isoformat()}.",
        model=model,
        model_settings=replace(model_settings or ModelSettings(), parallel_tool_calls=False),
        tools=[search_tool] if search_tool is not None else [],
        output_type=TopicProposal,
        tool_use_behavior=_finish_without_headlines,
    )
