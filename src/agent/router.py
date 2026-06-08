"""
Request-Router: bestimmt Modus (song | control) und filtert Tools.
"""
from __future__ import annotations

import logging

log = logging.getLogger("bitwig-agent")

_CONTROL_COMMANDS = frozenset([
    "/play", "/stop", "/tempo", "/select", "/mute", "/solo",
    "/volume", "/status", "/record", "/loop", "/undo",
])

_CONTROL_TOOL_NAMES = frozenset([
    "check_bitwig_connection", "control_bitwig",
    "bitwig_play", "bitwig_stop", "bitwig_set_tempo",
    "bitwig_select_track", "bitwig_set_track_volume",
    "bitwig_pan_track", "bitwig_solo_track", "bitwig_mute_track",
    "bitwig_eq_band",
])

# Tool-Sets nach Anfrage-Typ (max ~10 Tools pro Aufruf)
_TOOLS_KNOWLEDGE = frozenset([
    "query_bitwig_docs", "web_search", "find_audio_example",
    "get_song_context", "get_artist_context", "search_artist_song",
    "learn_song_from_youtube", "store_result_in_kb",
])

_TOOLS_PRODUCTION = frozenset([
    "query_bitwig_docs", "web_search", "find_audio_example",
    "check_bitwig_connection", "execute_setup", "compose_notes",
    "write_pattern", "write_pattern_raw", "get_bitwig_track_state",
    "validate_and_learn",
])

_TOOLS_PROJECT = frozenset([
    "scan_and_learn_project", "get_song_context", "get_bitwig_track_state",
    "reconstruct_project", "create_track_from_recipe", "store_result_in_kb",
])

_TOOLS_LAUNCHPAD = frozenset([
    "suggest_notes", "get_launchpad_mode", "listen_played_notes",
    "play_notes", "arm_track", "check_bitwig_connection",
])

# Schlüsselwörter → Tool-Set
_KEYWORD_SETS = [
    (_TOOLS_LAUNCHPAD,   ["launchpad", "spielen", "aufnehmen", "einspielen",
                          "arm", "suggest", "play notes"]),
    (_TOOLS_PROJECT,     ["projekt", "project", "scan", "rekonstruier", "lern das projekt"]),
    (_TOOLS_PRODUCTION,  ["erstelle", "schreibe", "baue", "mach", "pattern",
                          "drum", "bass", "lead", "setup", "track anlegen",
                          "komponiere", "erzeuge", "generiere"]),
    (_TOOLS_KNOWLEDGE,   ["kennst du", "welche songs", "welche genres", "erkläre",
                          "was ist", "wie klingt", "stil von", "wer ist",
                          "tonart", "bpm", "akkorde", "bassline", "melodie"]),
]

_CONFIRMATIONS = frozenset([
    "ja", "ja bitte", "ja!", "ok", "klar", "gut", "los",
    "mach das", "mach es", "alles klar", "bitte", "mach",
])

_NUDGE_PREFIXES = (
    "Deine Antwort war leer.",
    "Dein Tool-Call war ungültig",
)


def _route_request(text: str) -> str:
    """Gibt 'song' | 'control' zurück."""
    lower = text.lower().strip()
    if lower.startswith("/"):
        cmd = lower.split()[0]
        if cmd in _CONTROL_COMMANDS:
            return "control"
    return "song"


def _select_tool_set(text: str) -> frozenset | None:
    """Wählt passendes Tool-Set anhand von Schlüsselwörtern."""
    lower = text.lower()
    for tool_set, keywords in _KEYWORD_SETS:
        if any(kw in lower for kw in keywords):
            return tool_set
    return None  # → alle Tools


def _get_prompt_for_mode(mode: str) -> str:
    from src.agent.prompts import PROMPT_CONTROL, PROMPT_SONG
    return PROMPT_CONTROL if mode == "control" else PROMPT_SONG


def _filter_tools_for_mode(mode: str, all_tools: list, user_text: str = "") -> list:
    if mode == "control":
        filtered = [t for t in all_tools if getattr(t, "name", "") in _CONTROL_TOOL_NAMES]
        return filtered or all_tools

    # Song-Modus: Tool-Set nach Schlüsselwörtern wählen
    tool_set = _select_tool_set(user_text)
    if tool_set:
        filtered = [t for t in all_tools if getattr(t, "name", "") in tool_set]
        if filtered:
            return filtered
    return all_tools


def _latest_user_text(messages: list) -> str:
    from langchain_core.messages import HumanMessage
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            text = (m.content or "").strip()
            if text and not any(text.startswith(p) for p in _NUDGE_PREFIXES):
                return text
    return ""


def _latest_human_is_nudge(messages: list) -> bool:
    from langchain_core.messages import HumanMessage
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            text = (m.content or "").strip()
            return bool(text and any(text.startswith(p) for p in _NUDGE_PREFIXES))
    return False


def _is_knowledge_question(text: str) -> bool:
    lower = text.lower().strip()
    if lower.startswith("/"):
        return False
    if lower in _CONFIRMATIONS or any(
        lower == c or lower.startswith(c + " ") or lower.startswith(c + ",")
        for c in _CONFIRMATIONS
    ):
        return False
    return True


def _select_tools_for_context(all_messages: list, get_tools_fn) -> list:
    user_text = _latest_user_text(all_messages)
    mode      = _route_request(user_text)
    all_tools = get_tools_fn()
    tools     = _filter_tools_for_mode(mode, all_tools, user_text)
    log.info("Router: mode=%s → %d Tools: %s", mode, len(tools),
             [getattr(t, "name", "?") for t in tools])
    return tools
