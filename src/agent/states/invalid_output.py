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
        retry_result = _handle_invalid_output(
            ctx.response, ctx.system, ctx.messages, ctx.selected_tools,
            ctx.agent_state, ctx.updates,
        )
        if retry_result is not None:
            ctx.early_return = retry_result
        return ctx


def _handle_invalid_output(response, system, messages, selected_tools, state, updates) -> dict | None:
    if not _has_invalid_tool_output(response):
        return None
    retry      = state.get("retry_count", 0) + 1
    snippet    = (response.content or "")[:300]
    diagnostic = _classify_invalid_output(response)
    user_text  = _latest_user_text(state["messages"])
    outcome    = "abort" if retry >= 3 else "retry"
    log.warning("LLM: ungültiger Tool-Output (%s) — Regenerierung #%d", diagnostic, retry)
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

    if diagnostic == "xml_fragment":
        recovered = _recover_xml_fragment_once(system, messages, selected_tools, state)
        if recovered is not None:
            log.info("LLM: xml_fragment auto-recovered")
            get_event_bus().emit("invalid_tool_output_recovered", {
                "diagnostic": diagnostic,
                "phase": state.get("generation_phase", "idle"),
                "retry": retry,
            })
            _append_policy_feedback({
                "timestamp": datetime.now().isoformat(),
                "action": "invalid_tool_output_recovered", "diagnostic": diagnostic,
                "phase": state.get("generation_phase", "idle"), "retry": retry,
            })
            return {"messages": [recovered], "retry_count": state.get("retry_count", 0), **updates}

    if retry >= 3:
        return {"messages": [AIMessage(content=(
            "Abbruch: Wiederholt ungültige Tool-Ausgaben vom Modell. "
            "Bitte Anfrage erneut senden oder Prompt vereinfachen."
        ))], "retry_count": retry, **updates}

    nudge = HumanMessage(content=(
        "Dein Tool-Call war ungültig oder abgeschnitten. "
        "Generiere denselben Schritt erneut als gültigen Tool-Call. "
        "Kein Freitext, kein XML-Fragment, nur ein ausführbarer Tool-Call "
        "mit validen JSON-Args."
    ))
    return {"messages": [response, nudge], "retry_count": retry, **updates}


def _recover_xml_fragment_once(system, messages, selected_tools, state):
    from src.agent.tools import ALL_TOOLS
    from src.agent.llm_client import _get_llm, _log_token_usage
    from src.agent.recovery import _recover_xml_fragment_once as _fn
    return _fn(system, messages, selected_tools, state, lambda: ALL_TOOLS, _get_llm, _log_token_usage)
