"""
Builders for the topic planner and clusterer agents.

Both are tool-free: they only produce structured output that application code
validates before anything reaches the reader.
"""

from pathlib import Path
from datetime import date
from agents.models.interface import Model
from agents import Agent, ModelSettings

from backend.agents.topics.schemas import TopicSearch, TopicProposal
from backend.application.turn.request_state import RequestState

PLANNER_PROMPT: str = Path(__file__).with_name("planner_prompt.md").read_text(encoding="utf-8")
CLUSTERER_PROMPT: str = Path(__file__).with_name("clusterer_prompt.md").read_text(encoding="utf-8")
TOPIC_AGENT_MAX_TURNS: int = 2


def build_planner_agent(
    model: Model,
    model_settings: ModelSettings | None,
    today: date,
) -> Agent[RequestState]:
    """
    Build the agent that extracts the headline search from a request.
    """
    return Agent(
        name="topic_planner",
        instructions=f"{PLANNER_PROMPT}\nToday's date is {today.isoformat()}.",
        model=model,
        model_settings=model_settings or ModelSettings(),
        output_type=TopicSearch,
    )


def build_clusterer_agent(
    model: Model,
    model_settings: ModelSettings | None,
) -> Agent[RequestState]:
    """
    Build the agent that groups numbered headlines into neutral topics.
    """
    return Agent(
        name="topic_clusterer",
        instructions=CLUSTERER_PROMPT,
        model=model,
        model_settings=model_settings or ModelSettings(),
        output_type=TopicProposal,
    )
