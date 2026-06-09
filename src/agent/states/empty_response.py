"""EmptyResponseState — nudgt das LLM bei fehlenden oder falschen Tool-Calls."""
from __future__ import annotations
import logging
from langchain_core.messages import HumanMessage
from src.agent.router import _classify_task, _latest_user_text
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
        elif _needs_setup_tool_nudge(ctx.response, ctx.agent_state, ctx.updates):
            retry = ctx.agent_state.get("retry_count", 0) + 1
            log.info("Workflow: Song-Plan abgeschlossen — Setup-Nudge #%d", retry)
            nudge = HumanMessage(content=(
                "Deine Antwort war nur ein Plan. Der Nutzer will den Track in Bitwig erstellen. "
                "Rufe jetzt direkt `execute_setup` mit einem konkreten Song-Setup auf. "
                "Kein weiterer erklärender Text, nur Tool-Call."
            ))
            updates = {**ctx.updates, "generation_phase": "setup"}
            ctx.early_return = {"messages": [ctx.response, nudge],
                                "retry_count": retry, **updates}
        elif _needs_known_songs_nudge(ctx.response, ctx.agent_state):
            retry = ctx.agent_state.get("retry_count", 0) + 1
            log.info("Workflow: Songliste angefragt — Knowledge-Nudge #%d", retry)
            nudge = HumanMessage(content=(
                "Der Nutzer fragt, welche Songs du kennst. "
                "Rufe jetzt `list_known_songs` auf. "
                "Kein Freitext, kein Raten, nur Tool-Call."
            ))
            ctx.early_return = {"messages": [ctx.response, nudge],
                                "retry_count": retry, **ctx.updates}
        return ctx


def _needs_setup_tool_nudge(response, state: dict, updates: dict) -> bool:
    if getattr(response, "tool_calls", None):
        return False
    if not (getattr(response, "content", "") or "").strip():
        return False

    phase = updates.get("generation_phase", state.get("generation_phase", "idle"))
    if phase not in ("idle", "planning"):
        return False

    user_text = _latest_user_text(state.get("messages", []))
    return _classify_task(user_text) == "song_creation"


def _needs_known_songs_nudge(response, state: dict) -> bool:
    if getattr(response, "tool_calls", None):
        return False
    if not (getattr(response, "content", "") or "").strip():
        return False
    if _has_recent_tool_call(state.get("messages", []), "list_known_songs"):
        return False
    user_text = _latest_user_text(state.get("messages", [])).lower()
    if not user_text:
        return False
    asks_song_list = (
        "welche songs" in user_text
        or "welche lieder" in user_text
        or "songs kennst" in user_text
        or "lieder kennst" in user_text
        or "bekannte songs" in user_text
        or "gelernte songs" in user_text
        or "known songs" in user_text
    )
    return asks_song_list and _classify_task(user_text) == "knowledge"


def _has_recent_tool_call(messages: list, name: str) -> bool:
    for message in reversed(messages[-8:]):
        for tool_call in getattr(message, "tool_calls", None) or []:
            if tool_call.get("name") == name:
                return True
    return False
