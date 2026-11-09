"""
The Researcher agent: one definition shared by both source groups.

The prompt, tools, and output schema are identical for the liberal and
conservative runs. Only the trusted group, window, and outlets bound into the
tools differ, and every run starts with a fresh context holding just the
assignment. Findings are validated against saved evidence before being kept.
"""

from pathlib import Path
from dataclasses import dataclass
from datetime import date

from agents import Agent, ModelSettings, function_tool
from agents.models.interface import Model

from backend.agents.researcher.tools import GroupSourceTools
from backend.agents.researcher_findings import SourceGroup, ResearcherFindings
from backend.application.findings_validation import InvalidFindings, validate_findings
from backend.application.outlet_assignments import outlets_for_group
from backend.application.request_state import RequestState
from backend.application.structured_run import run_with_correction

PROMPT: str = Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")
RESEARCHER_MAX_TURNS: int = 12


@dataclass(frozen=True)
class ResearcherOutcome:
    """
    Validated findings, or the reason the Researcher produced none.
    """

    findings: ResearcherFindings | None
    failure: str | None = None


def build_researcher_agent(
    tools: GroupSourceTools,
    group: SourceGroup,
    model: Model,
    model_settings: ModelSettings | None,
) -> Agent[RequestState]:
    """
    Build the Researcher with tools bound to one group's trusted restrictions.
    """

    @function_tool
    async def search_articles(query: str) -> str:
        """
        Search the assigned outlets for candidate articles about the event.

        Args:
            query: Search words describing the event.
        """
        return (await tools.search_articles(query)).model_dump_json()

    @function_tool
    async def read_article(url: str, outlet_id: str) -> str:
        """
        Read and save the full text of one article from an assigned outlet.

        Args:
            url: The article URL, taken from search results.
            outlet_id: The outlet the article belongs to.
        """
        return (await tools.read_article(url, outlet_id)).model_dump_json()

    return Agent(
        name=f"researcher_{group.value}",
        instructions=PROMPT,
        model=model,
        model_settings=model_settings or ModelSettings(),
        tools=[search_articles, read_article],
        output_type=ResearcherFindings,
    )


def describe_assignment(
    group: SourceGroup,
    event: str,
    window: tuple[date, date],
    focus_question: str | None,
) -> str:
    """
    Describe one Researcher's assignment without any other group's findings.
    """
    return (
        f"Event: {event}\n"
        f"Source group: {group.value}\n"
        f"Assigned outlets: {', '.join(outlets_for_group(group))}\n"
        f"Publication window (inclusive): {window[0].isoformat()} to "
        f"{window[1].isoformat()}\n"
        f"Focus question: {focus_question or 'none; cover the event broadly'}"
    )


async def run_researcher(
    state: RequestState,
    group: SourceGroup,
    window: tuple[date, date],
    event: str,
    focus_question: str | None,
    model: Model,
    model_settings: ModelSettings | None,
) -> ResearcherOutcome:
    """
    Run one fresh-context Researcher and return validated findings or a failure.
    """
    tools: GroupSourceTools = GroupSourceTools(state, group, window)
    agent: Agent[RequestState] = build_researcher_agent(
        tools, group, model, model_settings
    )
    accepted: list[ResearcherFindings] = []

    def validate(output: ResearcherFindings) -> str | None:
        """
        Force the trusted group, then check citations against saved evidence.
        """
        candidate: ResearcherFindings = output.model_copy(update={"group": group})
        try:
            validate_findings(
                candidate, state.store.list_articles(state.conversation_id)
            )
        except InvalidFindings as error:
            return f"{error} Cite only articles you read successfully."
        accepted.append(candidate)
        return None

    assignment: str = describe_assignment(group, event, window, focus_question)
    output, problem = await run_with_correction(
        agent,
        [{"role": "user", "content": assignment}],
        state,
        validate,
        RESEARCHER_MAX_TURNS,
    )
    if output is None:
        return ResearcherOutcome(None, problem)
    return ResearcherOutcome(accepted[-1])
