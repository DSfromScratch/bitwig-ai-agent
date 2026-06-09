"""Request-Router: bestimmt Modus, Workflow-Phase und passende Tool-Auswahl."""
from __future__ import annotations

import logging

log = logging.getLogger("bitwig-agent")

# ── Slash-Commands (deterministisch, kein LLM nötig) ─────────────────────────

_CONTROL_COMMANDS = frozenset([
    "/play", "/stop", "/tempo", "/select", "/mute", "/solo",
    "/volume", "/status", "/record", "/loop", "/undo",
])

# ── Tool-Name-Sets pro Domäne / Phase ────────────────────────────────────────

_CONTROL_TOOL_NAMES = frozenset([
    "check_bitwig_connection", "control_bitwig",
    "bitwig_play", "bitwig_stop", "bitwig_set_tempo",
    "bitwig_select_track", "bitwig_set_track_volume",
    "bitwig_pan_track", "bitwig_solo_track", "bitwig_mute_track",
    "bitwig_eq_band",
])

_TOOLS_KNOWLEDGE = frozenset([
    "query_bitwig_docs", "web_search", "find_audio_example",
    "get_song_context", "get_artist_context", "search_artist_song",
    "learn_song_from_youtube", "store_result_in_kb", "list_known_songs",
])

_TOOLS_PLANNING = frozenset([
    "query_bitwig_docs", "get_song_context", "get_artist_context",
    "search_artist_song", "web_search", "find_audio_example", "list_known_songs",
])

_TOOLS_SETUP = frozenset([
    "check_bitwig_connection", "execute_setup", "get_bitwig_track_state",
    "scan_vst_plugins", "create_track_from_recipe",
])

_TOOLS_STATUS = frozenset([
    "check_bitwig_connection", "get_bitwig_track_state",
])

_TOOLS_GENERATING = frozenset([
    "play_notes", "get_bitwig_track_state", "validate_music", "validate_and_learn",
])

_TOOLS_VERIFYING = frozenset([
    "get_bitwig_track_state", "validate_music", "validate_and_learn",
    "analyze_song", "store_result_in_kb",
])

_TOOLS_PROJECT = frozenset([
    "scan_and_learn_project", "get_song_context", "get_bitwig_track_state",
    "reconstruct_project", "create_track_from_recipe", "store_result_in_kb",
])

_TOOLS_LAUNCHPAD = frozenset([
    "suggest_notes", "get_launchpad_mode", "listen_played_notes",
    "play_notes", "arm_track", "check_bitwig_connection",
])

_TOOLS_SONG_DEFAULT = _TOOLS_PLANNING
_TOOLS_PRODUCTION   = _TOOLS_PLANNING | _TOOLS_SETUP | _TOOLS_GENERATING

_WORKFLOW_TOOLS = {
    "idle":      _TOOLS_PLANNING,
    "planning":  _TOOLS_PLANNING,
    "setup":     _TOOLS_SETUP,
    "generating": _TOOLS_GENERATING,
    "verifying": _TOOLS_VERIFYING,
    "done":      _TOOLS_PLANNING,
    "error":     _TOOLS_PLANNING,
}

# ── Sonstige Konstanten ───────────────────────────────────────────────────────

_CONFIRMATIONS = frozenset([
    "ja", "ja bitte", "ja!", "ok", "klar", "gut", "los",
    "mach das", "mach es", "alles klar", "bitte", "mach",
])

_NUDGE_PREFIXES = (
    "Deine Antwort war leer.",
    "Dein Tool-Call war ungültig",
    "Deine Antwort war nur ein Plan.",
    "Der Nutzer will einen Beat hören.",
    "Der Nutzer will das Launchpad benutzen.",
    "Der Nutzer fragt, welche Songs du kennst.",
    "Der Nutzer fragt nach dem Bitwig-Status.",
    "Die Notengenerierung braucht jetzt",
)

_SETUP_DONE_TOOLS  = frozenset(["execute_setup", "create_track_from_recipe", "reconstruct_project"])
_NOTES_DONE_TOOLS  = frozenset(["play_notes"])
_VERIFY_DONE_TOOLS = frozenset(["validate_music", "validate_and_learn", "analyze_song"])

# ── LLM-Intent-Klassifikation ─────────────────────────────────────────────────

_INTENT_CATEGORIES = frozenset([
    "control", "knowledge", "status", "project",
    "launchpad", "song_creation", "song_default",
])

_INTENT_SYSTEM = (
    "Classify the music production request into exactly one category.\n"
    "Reply with ONLY the category name — no explanation, no punctuation.\n\n"
    "control      → /play /stop /tempo /mute /volume (explicit slash-command)\n"
    "knowledge    → question about theory, artists, songs, genres, style\n"
    "status       → how many tracks, what is open in Bitwig, current state\n"
    "project      → scan project, reconstruct, recipe from existing project\n"
    "launchpad    → play notes live, arm track, listen to input\n"
    "song_creation → create / compose / write something new in Bitwig\n"
    "song_default → anything else"
)


def classify_intent_llm(text: str) -> str:
    """Schneller LLM-Call (max 15 Token) zur Intent-Klassifikation.

    Gibt eine Kategorie aus _INTENT_CATEGORIES zurück.
    Fällt auf 'song_default' zurück wenn der Server nicht erreichbar ist.
    """
    if not text.strip():
        return "song_default"
    if text.strip().startswith("/") and text.strip().split()[0] in _CONTROL_COMMANDS:
        return "control"

    try:
        from src.agent.llm_client import _get_llm
        from langchain_core.messages import SystemMessage, HumanMessage as _HM
        llm = _get_llm(max_tokens=15, temperature=0.0)
        response = llm.invoke([
            SystemMessage(content=_INTENT_SYSTEM),
            _HM(content=text[:300]),
        ])
        raw = (response.content or "").strip().lower().split()[0] if response.content else ""
        if raw in _INTENT_CATEGORIES:
            log.debug("Intent: '%s' → %s", text[:60], raw)
            return raw
        log.warning("classify_intent_llm: unbekannte Kategorie '%s' — fallback song_default", raw)
    except Exception as exc:
        log.warning("classify_intent_llm fehlgeschlagen: %s — fallback song_default", exc)
    return "song_default"


def _classify_task(text: str, intent: str | None = None) -> str:
    """Gibt Task-Kategorie zurück. Nutzt pre-computed intent wenn vorhanden."""
    if intent and intent in _INTENT_CATEGORIES:
        return intent
    return classify_intent_llm(text)


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _route_request(text: str) -> str:
    """Gibt 'song' | 'control' zurück."""
    lower = text.lower().strip()
    if lower.startswith("/"):
        cmd = lower.split()[0]
        if cmd in _CONTROL_COMMANDS:
            return "control"
    return "song"


def _is_confirmation(text: str) -> bool:
    lower = text.lower().strip()
    return bool(lower and (
        lower in _CONFIRMATIONS or any(
            lower == c or lower.startswith(c + " ") or lower.startswith(c + ",")
            for c in _CONFIRMATIONS
        )
    ))


def _tool_names_for_context(mode: str, phase: str, intent: str) -> frozenset:
    if mode == "control":
        return _CONTROL_TOOL_NAMES
    if intent == "launchpad":
        return _TOOLS_LAUNCHPAD
    if intent == "status":
        return _TOOLS_STATUS
    if intent == "project":
        return _TOOLS_PROJECT
    if intent == "knowledge":
        return _TOOLS_KNOWLEDGE
    return _WORKFLOW_TOOLS.get(phase, _TOOLS_SONG_DEFAULT)


def _filter_tools_for_mode(
    mode: str,
    all_tools: list,
    intent: str = "song_default",
    phase: str = "idle",
) -> list:
    tool_names = _tool_names_for_context(mode, phase, intent)
    filtered = [t for t in all_tools if getattr(t, "name", "") in tool_names]
    if filtered:
        return filtered
    log.warning("Router: kein Tool aus Set %s gefunden — fallback auf alle Tools", sorted(tool_names))
    return all_tools


def _get_prompt_for_mode(mode: str) -> str:
    from src.agent.prompts import PROMPT_CONTROL, PROMPT_SONG
    return PROMPT_CONTROL if mode == "control" else PROMPT_SONG


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


def _tool_call_names(messages: list) -> list[str]:
    names: list[str] = []
    for message in reversed(messages):
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            names.extend(str(tc.get("name", "")) for tc in tool_calls if tc.get("name"))
            break
    return names


def _phase_after_recent_tools(messages: list, current_phase: str) -> str:
    for message in reversed(messages):
        tool_names = {str(tc.get("name", "")) for tc in (getattr(message, "tool_calls", None) or [])}
        if tool_names & _VERIFY_DONE_TOOLS:
            return "done"
        if tool_names & _NOTES_DONE_TOOLS:
            return "verifying"
        if tool_names & _SETUP_DONE_TOOLS:
            return "verifying"
    return current_phase


def _phase_after_confirmation(text: str, current_phase: str) -> str:
    if not _is_confirmation(text):
        return current_phase
    if current_phase in ("idle", "planning"):
        return "planning"
    if current_phase == "setup":
        return "verifying"
    if current_phase == "generating":
        return "verifying"
    return current_phase


def _effective_generation_phase(messages: list, current_phase: str, user_text: str) -> str:
    phase = _phase_after_recent_tools(messages, current_phase)
    if phase == "idle" and _route_request(user_text) == "song":
        phase = "planning"
    return _phase_after_confirmation(user_text, phase)


def _select_tools_for_context(
    all_messages: list,
    get_tools_fn,
    generation_phase: str = "idle",
    intent: str | None = None,
) -> list:
    user_text = _latest_user_text(all_messages)
    mode = _route_request(user_text)
    phase = _effective_generation_phase(all_messages, generation_phase, user_text)
    resolved_intent = intent or _classify_task(user_text)
    all_tools = get_tools_fn()
    tools = _filter_tools_for_mode(mode, all_tools, intent=resolved_intent, phase=phase)
    log.info(
        "Router: mode=%s phase=%s intent=%s -> %d Tools: %s",
        mode, phase, resolved_intent, len(tools), [getattr(t, "name", "?") for t in tools],
    )
    return tools
