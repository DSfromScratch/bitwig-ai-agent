"""FinalizeState — loggt Tool-Calls / Antwort und baut das Return-Dict."""
from __future__ import annotations
import logging
from src.agent.states.base import AgentPhaseState, PhaseContext

log = logging.getLogger("bitwig-agent")


class FinalizeState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        from src.agent.events import get_event_bus
        has_tool_calls = bool(getattr(ctx.response, "tool_calls", None))
        if has_tool_calls:
            for tc in ctx.response.tool_calls:
                log.info("Tool-Call: %s(%s)", tc["name"], str(tc.get("args", {}))[:120])
                get_event_bus().emit("tool_call", {
                    "name": tc["name"],
                    "args": tc.get("args", {}),
                })
        else:
            log.info("Agent-Antwort: %s", (ctx.response.content or "")[:200])
        ctx.updates["messages"] = [ctx.response]
        return ctx
