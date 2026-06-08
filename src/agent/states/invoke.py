"""InvokeState — ruft das LLM auf (mit Kontext-Overflow-Fallback)."""
from __future__ import annotations
import logging
from langchain_core.messages import SystemMessage
from openai import BadRequestError
from src.agent.llm_client import _get_llm, _log_token_usage
from src.agent.prompts import PROMPT_CONTROL
from src.agent.states.base import AgentPhaseState, PhaseContext

log = logging.getLogger("bitwig-agent")


class InvokeState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        ctx.response = _invoke_with_retry(ctx.system, ctx.messages, ctx.selected_tools)
        return ctx


def _invoke_with_retry(system: SystemMessage, messages: list, selected_tools: list):
    from src.agent.tools import ALL_TOOLS
    llm = _get_llm().bind_tools(selected_tools) if selected_tools else _get_llm()
    try:
        response = llm.invoke([system] + messages)
        _log_token_usage(response, label="main")
        return response
    except BadRequestError as exc:
        msg = str(exc)
        if "maximum context length" not in msg and "input_tokens" not in msg:
            raise
        fallback_tools = [t for t in ALL_TOOLS
                          if getattr(t, "name", "") in {"check_bitwig_connection", "execute_setup"}]
        fallback_llm = _get_llm(max_tokens=700).bind_tools(fallback_tools or selected_tools)
        log.warning("LLM Kontextlimit — Fallback mit %d Tools, max_tokens=700",
                    len(fallback_tools or selected_tools))
        try:
            response = fallback_llm.invoke([SystemMessage(content=PROMPT_CONTROL)] + messages[-6:])
            _log_token_usage(response, label="fallback")
            return response
        except Exception as fallback_exc:
            log.error("LLM Fallback fehlgeschlagen: %s", fallback_exc, exc_info=True)
            from src.agent.events import get_event_bus
            get_event_bus().emit("agent_error", {
                "source": "llm_fallback",
                "error": type(fallback_exc).__name__,
                "message": str(fallback_exc),
            })
            raise RuntimeError(
                f"LLM nicht erreichbar — Kontext zu groß, Fallback fehlgeschlagen: {fallback_exc}"
            ) from fallback_exc
