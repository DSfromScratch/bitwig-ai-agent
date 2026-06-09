"""EmptyResponseState — nudgt das LLM bei fehlenden oder falschen Tool-Calls."""
from __future__ import annotations
import logging
from langchain_core.messages import HumanMessage
from src.agent.router import _latest_user_text
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
        elif _needs_launchpad_tool_nudge(ctx.response, ctx.agent_state, intent=ctx.intent):
            retry = ctx.agent_state.get("retry_count", 0) + 1
            log.info("Workflow: Launchpad-Anfrage nur als Text beantwortet — Tool-Nudge #%d", retry)
            user_text = _latest_user_text(ctx.agent_state.get("messages", []))
            if _is_launchpad_play_request(user_text):
                content = (
                    "Der Nutzer will einen Beat hören. "
                    "Rufe jetzt direkt `play_notes` mit einem einfachen Drum-Beat auf. "
                    "Kein Freitext, keine Absichtserklärung, nur Tool-Call."
                )
            else:
                content = (
                    "Der Nutzer will das Launchpad benutzen. "
                    "Rufe jetzt direkt ein passendes Launchpad-Tool auf: "
                    "`check_bitwig_connection`, `get_launchpad_mode`, `arm_track`, "
                    "`suggest_notes`, `play_notes` oder `listen_played_notes`. "
                    "Kein Freitext, keine Absichtserklärung, nur Tool-Call."
                )
            nudge = HumanMessage(content=content)
            ctx.early_return = {"messages": [ctx.response, nudge],
                                "retry_count": retry, **ctx.updates}
        elif _needs_status_tool_nudge(ctx.response, ctx.agent_state, intent=ctx.intent):
            retry = ctx.agent_state.get("retry_count", 0) + 1
            log.info("Workflow: Bitwig-Status nur als Text beantwortet — Status-Nudge #%d", retry)
            nudge = HumanMessage(content=(
                "Der Nutzer fragt nach dem Bitwig-Status. "
                "Rufe jetzt direkt `check_bitwig_connection` oder `get_bitwig_track_state` auf. "
                "Kein Freitext, keine Absichtserklärung, nur Tool-Call."
            ))
            ctx.early_return = {"messages": [ctx.response, nudge],
                                "retry_count": retry, **ctx.updates}
        elif _needs_setup_tool_nudge(ctx.response, ctx.agent_state, ctx.updates, intent=ctx.intent):
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
        elif _needs_known_songs_nudge(ctx.response, ctx.agent_state, intent=ctx.intent):
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


def _needs_setup_tool_nudge(response, state: dict, updates: dict, intent: str | None = None) -> bool:
    if getattr(response, "tool_calls", None):
        return False
    if not (getattr(response, "content", "") or "").strip():
        return False

    phase = updates.get("generation_phase", state.get("generation_phase", "idle"))
    if phase not in ("idle", "planning"):
        return False

    return intent == "song_creation"


def _needs_launchpad_tool_nudge(response, state: dict, intent: str | None = None) -> bool:
    if getattr(response, "tool_calls", None):
        return False
    if not (getattr(response, "content", "") or "").strip():
        return False
    if intent != "launchpad":
        return False
    user_text = _latest_user_text(state.get("messages", []))
    if _is_launchpad_play_request(user_text):
        return not _has_recent_tool_call(state.get("messages", []), "play_notes")
    if _has_recent_tool_call_any(
        state.get("messages", []),
        {
            "check_bitwig_connection", "get_launchpad_mode", "arm_track",
            "suggest_notes", "play_notes", "listen_played_notes",
        },
    ):
        return False
    return True


def _needs_status_tool_nudge(response, state: dict, intent: str | None = None) -> bool:
    if getattr(response, "tool_calls", None):
        return False
    if not (getattr(response, "content", "") or "").strip():
        return False
    if _has_recent_tool_call(state.get("messages", []), "get_bitwig_track_state"):
        return False
    return intent == "status"


def _is_launchpad_play_request(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in (
        "spiel", "spiele", "abspiel", "beat", "drum", "rhythm", "groove",
    ))


def _needs_known_songs_nudge(response, state: dict, intent: str | None = None) -> bool:
    if getattr(response, "tool_calls", None):
        return False
    if not (getattr(response, "content", "") or "").strip():
        return False
    if _has_recent_tool_call(state.get("messages", []), "list_known_songs"):
        return False
    if intent != "knowledge":
        return False
    user_text = _latest_user_text(state.get("messages", [])).lower()
    if not user_text:
        return False
    return (
        "welche songs" in user_text
        or "welche lieder" in user_text
        or "songs kennst" in user_text
        or "lieder kennst" in user_text
        or "bekannte songs" in user_text
        or "gelernte songs" in user_text
        or "known songs" in user_text
    )


def _has_recent_tool_call(messages: list, name: str) -> bool:
    return _has_recent_tool_call_any(messages, {name})


def _has_recent_tool_call_any(messages: list, names: set[str]) -> bool:
    for message in reversed(messages[-8:]):
        for tool_call in getattr(message, "tool_calls", None) or []:
            if tool_call.get("name") in names:
                return True
    return False
