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
                if not isinstance(tc, dict):
                    log.warning("FinalizeState: tc ist kein dict: %r", tc)
                    continue
                name = tc.get("name") or tc.get("function", {}).get("name", "?")
                if not name or name == "?":
                    log.warning("FinalizeState: tc ohne name-Feld: %r", tc)
                log.info("Tool-Call: %s(%s)", name, str(tc.get("args", {}))[:120])
                get_event_bus().emit("tool_call", {
                    "name": name or "?",
                    "args": tc.get("args", {}),
                })
        else:
            log.info("Agent-Antwort: %s", (ctx.response.content or "")[:200])
        ctx.updates["messages"] = [ctx.response]
        return ctx
