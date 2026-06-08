"""InvokeState — ruft das LLM auf (mit Kontext-Overflow-Fallback)."""
from __future__ import annotations
import logging
import time
from httpx import ConnectError
from openai import APIConnectionError, BadRequestError
from langchain_core.messages import SystemMessage
from src.agent.llm_client import _get_llm, _log_token_usage
from src.agent.prompts import PROMPT_CONTROL
from src.agent.states.base import AgentPhaseState, PhaseContext

log = logging.getLogger("bitwig-agent")


class InvokeState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        ctx.response = _invoke_with_retry(ctx.system, ctx.messages, ctx.selected_tools)
        return ctx


def _trim_tool_descriptions(tools: list, max_chars: int = 80) -> list:
    """Kürzt Tool-Beschreibungen um Token-Verbrauch zu reduzieren (OOM-Schutz)."""
    import copy
    trimmed = []
    for t in tools:
        t2 = copy.copy(t)
        desc = getattr(t2, "description", "") or ""
        if len(desc) > max_chars:
            # Erste Zeile oder erste max_chars Zeichen
            first_line = desc.split("\n")[0].strip()
            t2.description = first_line[:max_chars] if first_line else desc[:max_chars]
        trimmed.append(t2)
    return trimmed


def _invoke_with_retry(system: SystemMessage, messages: list, selected_tools: list):
    from src.agent.tools import ALL_TOOLS
    slim_tools = _trim_tool_descriptions(selected_tools) if selected_tools else []
    llm = _get_llm().bind_tools(slim_tools) if slim_tools else _get_llm()
    # Retry bei ConnectError (Server-OOM-Crash → LaunchAgent startet ihn neu)
    for attempt in range(3):
        try:
            response = llm.invoke([system] + messages)
            _log_token_usage(response, label="main")
            return response
        except (ConnectError, APIConnectionError) as exc:
            if attempt < 2:
                wait = 5 * (attempt + 1)
                log.warning("LLM nicht erreichbar (Versuch %d/3) — warte %ds: %s", attempt + 1, wait, exc)
                time.sleep(wait)
                continue
            raise
        except BadRequestError as exc:
            msg = str(exc)
            if "maximum context length" not in msg and "input_tokens" not in msg:
                raise
            break  # Kontext-Fehler → Fallback
    else:
        raise RuntimeError("LLM nach 3 Versuchen nicht erreichbar.")

    # Fallback bei Kontextüberschreitung
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
