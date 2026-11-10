"""
Run an agent to structured output with budget enforcement and one correction.

Every agent run in the application goes through here so that model-call
budgets, tracing configuration, and the single bounded correction attempt are
applied consistently and in code rather than left to prompts."""

from typing import cast
from collections.abc import Callable
from agents.exceptions import ModelBehaviorError
from agents import (
    Agent,
    Runner,
    RunHooks,
    RunConfig,
    RunResult,
    RunContextWrapper,
    TResponseInputItem,
)

from backend.application.turn.request_state import RequestState
from backend.application.turn.request_budget import BudgetResource

RUN_CONFIG: RunConfig = RunConfig(tracing_disabled=True)
MAXIMUM_ATTEMPTS: int = 2


class BudgetExceeded(Exception):
    """
    Raised when the request's model-call budget or deadline is used up.
    """


class BudgetHooks(RunHooks[RequestState]):
    """
    Count every model call against the shared request budget.
    """

    async def on_llm_start(
        self,
        context: RunContextWrapper[RequestState],
        agent: Agent[RequestState],
        system_prompt: str | None,
        input_items: list[TResponseInputItem],
    ) -> None:
        """
        Refuse the model call when the shared budget no longer allows it.
        """
        state: RequestState = context.context
        if not state.budget.try_consume(BudgetResource.MODEL_CALLS):
            raise BudgetExceeded("The model-call budget for this request is used up.")


async def run_with_correction[Output](
    agent: Agent[RequestState],
    input_items: list[TResponseInputItem],
    state: RequestState,
    validate: Callable[[Output], str | None],
    max_turns: int,
) -> tuple[Output | None, str | None]:
    """
    Run the agent, allowing one correction if its output is rejected.

    Returns the valid output and no problem, or no output and the last problem.
    Budget and turn-limit exceptions propagate to the caller. A correction
    continues the same conversation so completed tool work is not repeated."""
    items: list[TResponseInputItem] = list(input_items)
    problem: str | None = None
    hooks: BudgetHooks = BudgetHooks()
    correction: str
    for _ in range(MAXIMUM_ATTEMPTS):
        try:
            result: RunResult = await Runner.run(
                agent,
                items,
                context=state,
                max_turns=max_turns,
                hooks=hooks,
                run_config=RUN_CONFIG,
            )
        except ModelBehaviorError:
            problem = "Your last reply was not valid structured output."
            correction = f"Correction needed: {problem}"
        else:
            # The SDK validates against the output type set on the agent.
            output: Output = cast(Output, result.final_output)
            problem = validate(output)
            if problem is None:
                return output, None
            items = result.to_input_list()
            correction = f"Your output was rejected: {problem} Correct it."
        items = [*items, {"role": "user", "content": correction}]
    return None, problem
