"""EmptyResponseState — nudgt das LLM wenn kein Tool-Call produziert wurde."""
from __future__ import annotations
import logging
from langchain_core.messages import HumanMessage
from src.agent.states.base import AgentPhaseState, PhaseContext

log = logging.getLogger("bitwig-agent")

# Intents die immer einen Tool-Call erfordern
_ACTION_INTENTS = frozenset([
    "control", "status", "project", "launchpad", "song_creation",
])


class EmptyResponseState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        if getattr(ctx.response, "tool_calls", None):
            return ctx

        retry = ctx.agent_state.get("retry_count", 0)
        if retry >= 3:
            return ctx

        has_content = bool((ctx.response.content or "").strip())
        needs_nudge = (
            not has_content                              # leere Antwort (think-only)
            or ctx.intent in _ACTION_INTENTS             # Text ohne Tool-Call bei Action-Intent
        )

        if needs_nudge:
            retry_new = retry + 1
            log.warning("LLM: kein Tool-Call (intent=%s) — Nudge #%d", ctx.intent, retry_new)
            nudge = HumanMessage(content=(
                "Deine Antwort enthielt keinen Tool-Call. "
                "Ruf jetzt direkt das passende Tool auf. "
                "Kein Text, nur Tool-Call."
            ))
            ctx.early_return = {
                "messages": [ctx.response, nudge],
                "retry_count": retry_new,
                **ctx.updates,
            }

        return ctx
