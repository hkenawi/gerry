"""
Run an agent to structured output with budget enforcement and one correction.

Every agent run in the application goes through here so that model-call
budgets, tracing configuration, and the single bounded correction attempt are
applied consistently and in code rather than left to prompts.
"""

from typing import Any, Callable

from agents import Agent, Runner, RunHooks, RunConfig
from agents.exceptions import ModelBehaviorError

from backend.application.request_state import RequestState
from backend.application.request_budget import BudgetResource

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
        context: Any,
        agent: Any,
        system_prompt: str | None,
        input_items: list[Any],
    ) -> None:
        """
        Refuse the model call when the shared budget no longer allows it.
        """
        state: RequestState = context.context
        if not state.budget.try_consume(BudgetResource.MODEL_CALLS):
            raise BudgetExceeded("The model-call budget for this request is used up.")


async def run_with_correction(
    agent: Agent[RequestState],
    input_items: list[dict[str, Any]],
    state: RequestState,
    validate: Callable[[Any], str | None],
    max_turns: int,
    enforce_budget: bool = True,
) -> tuple[Any | None, str | None]:
    """
    Run the agent, allowing one correction if its output is rejected.

    Returns the valid output and no problem, or no output and the last problem.
    Budget and turn-limit exceptions propagate to the caller. A correction
    continues the same conversation so completed tool work is not repeated.
    """
    items: list[Any] = list(input_items)
    problem: str | None = None
    hooks: BudgetHooks | None = BudgetHooks() if enforce_budget else None
    for _ in range(MAXIMUM_ATTEMPTS):
        try:
            result = await Runner.run(
                agent,
                items,
                context=state,
                max_turns=max_turns,
                hooks=hooks,
                run_config=RUN_CONFIG,
            )
        except ModelBehaviorError:
            problem = "Your last reply was not valid structured output."
            items = [
                *items,
                {"role": "user", "content": f"Correction needed: {problem}"},
            ]
            continue
        problem = validate(result.final_output)
        if problem is None:
            return result.final_output, None
        items = [
            *result.to_input_list(),
            {
                "role": "user",
                "content": f"Your output was rejected: {problem} Correct it.",
            },
        ]
    return None, problem
