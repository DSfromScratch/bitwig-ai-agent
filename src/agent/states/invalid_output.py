"""InvalidOutputState — behandelt kaputte Tool-Ausgaben (Retry / Abort)."""
from __future__ import annotations
import logging
from datetime import datetime
from langchain_core.messages import AIMessage, HumanMessage
from src.agent.recovery import _classify_invalid_output, _has_invalid_tool_output
from src.agent.router import _latest_user_text
from src.agent.states.base import AgentPhaseState, PhaseContext
from src.agent.states.shared import _append_policy_feedback

log = logging.getLogger("bitwig-agent")


class InvalidOutputState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        # Auto-patch XML-fragment tool calls (Qwen3 produziert gelegentlich <tool_call>-Format)
        from src.agent.recovery import _recover_tool_calls
        ctx.response = _recover_tool_calls(ctx.response, ctx.agent_state)

        retry_result = _handle_invalid_output(
            ctx.response, ctx.agent_state, ctx.updates,
        )
        if retry_result is not None:
            ctx.early_return = retry_result
        return ctx


def _handle_invalid_output(response, state, updates) -> dict | None:
    if not _has_invalid_tool_output(response):
        return None

    retry = state.get("retry_count", 0) + 1
    snippet = (response.content or "")[:300]
    diagnostic = _classify_invalid_output(response)
    user_text = _latest_user_text(state["messages"])
    outcome = "abort" if retry >= 3 else "retry"

    log.warning("LLM: ungültiger Tool-Output (%s) — Nudge #%d", diagnostic, retry)
    from src.agent.events import get_event_bus
    get_event_bus().emit("invalid_tool_output", {
        "diagnostic": diagnostic, "phase": state.get("generation_phase", "idle"),
        "retry": retry, "snippet": snippet, "outcome": outcome,
        "user_prompt": user_text[:200],
    })
    _append_policy_feedback({
        "timestamp": datetime.now().isoformat(),
        "action": "invalid_tool_output", "diagnostic": diagnostic,
        "phase": state.get("generation_phase", "idle"), "retry": retry,
        "snippet": snippet, "outcome": outcome, "user_prompt": user_text[:200],
    })

    if retry >= 3:
        return {"messages": [AIMessage(content=(
            "Abbruch: Wiederholt ungültige Tool-Ausgaben vom Modell. "
            "Bitte Anfrage erneut senden oder Prompt vereinfachen."
        ))], "retry_count": retry, **updates}

    nudge = HumanMessage(content=(
        "Dein Tool-Call war ungültig oder abgeschnitten. "
        "Generiere einen gültigen Tool-Call mit validen JSON-Args. "
        "Kein Freitext, kein XML-Fragment, nur Tool-Call."
    ))
    return {"messages": [response, nudge], "retry_count": retry, **updates}
