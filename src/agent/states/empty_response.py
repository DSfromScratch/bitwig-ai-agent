"""EmptyResponseState — nudgt das LLM wenn es nur Think-Only geantwortet hat."""
from __future__ import annotations
import logging
from langchain_core.messages import HumanMessage
from src.agent.states.base import AgentPhaseState, PhaseContext

log = logging.getLogger("bitwig-agent")


class EmptyResponseState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        has_tool_calls = bool(getattr(ctx.response, "tool_calls", None))
        if not has_tool_calls and not (ctx.response.content or "").strip():
            retry = ctx.agent_state.get("retry_count", 0) + 1
            log.warning("LLM: leere Antwort (think-only) — Nudge #%d", retry)
            nudge = HumanMessage(content=(
                "Deine Antwort war leer. Bitte ruf jetzt direkt ein "
                "passendes Tool auf. Kein Text, nur Tool-Call."
            ))
            ctx.early_return = {"messages": [ctx.response, nudge],
                                "retry_count": retry, **ctx.updates}
        return ctx
