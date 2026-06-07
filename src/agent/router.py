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

_SONG_TOOL_NAMES = frozenset([
    "check_bitwig_connection", "execute_setup",
    "get_bitwig_track_state", "query_bitwig_docs",
    "write_pattern", "write_pattern_raw", "compose_notes", "scan_vst_plugins",
    "validate_music", "validate_and_learn", "analyze_song", "export_mlx_training_data",
    "suggest_notes", "get_launchpad_mode", "listen_played_notes",
    "play_notes", "arm_track",
    "scan_and_learn_project",
    "reconstruct_project",
    "create_track_from_recipe",
])

_CONTROL_TOOL_NAMES = frozenset([
    "check_bitwig_connection", "control_bitwig",
    "bitwig_play", "bitwig_stop", "bitwig_set_tempo",
    "bitwig_select_track", "bitwig_set_track_volume",
    "bitwig_pan_track", "bitwig_solo_track", "bitwig_mute_track",
    "bitwig_eq_band",
])

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


def _get_prompt_for_mode(mode: str) -> str:
    from src.agent.prompts import PROMPT_CONTROL, PROMPT_SONG
    return PROMPT_CONTROL if mode == "control" else PROMPT_SONG


def _filter_tools_for_mode(mode: str, all_tools: list) -> list:
    allowed  = _CONTROL_TOOL_NAMES if mode == "control" else _SONG_TOOL_NAMES
    filtered = [t for t in all_tools if getattr(t, "name", "") in allowed]
    if not filtered:
        return [t for t in all_tools if getattr(t, "name", "") == "check_bitwig_connection"] or all_tools
    return filtered


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
    tools     = _filter_tools_for_mode(mode, all_tools)
    log.info("Router: mode=%s → %d Tools: %s", mode, len(tools),
             [getattr(t, "name", "?") for t in tools])
    return tools
