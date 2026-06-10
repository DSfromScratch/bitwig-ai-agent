"""Request-Router: bestimmt Modus, Workflow-Phase und System-Prompt."""
from __future__ import annotations

import logging
from src.agent.config import config

log = logging.getLogger("bitwig-agent")

# ── Slash-Commands (deterministisch, kein LLM nötig) ─────────────────────────

_CONTROL_COMMANDS = frozenset([
    "/play", "/stop", "/tempo", "/select", "/mute", "/solo",
    "/volume", "/status", "/record", "/loop", "/undo",
])

_GREETINGS = frozenset([
    "hallo", "hi", "hey", "hello", "servus", "moin", "guten morgen",
    "guten tag", "guten abend", "na", "jo", "yo",
])

# ── Sonstige Konstanten ───────────────────────────────────────────────────────

_CONFIRMATIONS = frozenset([
    "ja", "ja bitte", "ja!", "ok", "klar", "gut", "los",
    "mach das", "mach es", "alles klar", "bitte", "mach",
])

_NUDGE_PREFIXES = (
    "Deine Antwort enthielt keinen Tool-Call.",  # EmptyResponseState
    "Dein Tool-Call war ungültig",               # InvalidOutputState
)

_SETUP_DONE_TOOLS  = frozenset(["execute_setup", "create_track_from_recipe", "reconstruct_project"])
_NOTES_DONE_TOOLS  = frozenset(["write_pattern_raw", "generate_pattern"])
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
    "status       → EXPLICIT question about Bitwig state: 'how many tracks?', 'what is open?'\n"
    "project      → scan project, reconstruct, recipe from existing project\n"
    "launchpad    → play notes live, arm track, listen to input\n"
    "song_creation → create / compose / write something new in Bitwig\n"
    "song_default → greetings, chitchat, unclear requests, anything else"
)


def classify_intent_llm(text: str) -> str:
    """Schneller LLM-Call (max 15 Token) zur Intent-Klassifikation.

    Gibt eine Kategorie aus _INTENT_CATEGORIES zurück.
    Fällt auf 'song_default' zurück wenn der Server nicht erreichbar ist.
    """
    if not text.strip():
        return "song_default"
    if text.strip().lower() in _GREETINGS:
        return "song_default"
    if text.strip().startswith("/") and text.strip().split()[0] in _CONTROL_COMMANDS:
        return "control"

    try:
        from src.agent.llm_client import _get_llm
        from langchain_core.messages import SystemMessage, HumanMessage as _HM
        llm = _get_llm(max_tokens=config.llm_intent_max_tokens, temperature=0.0)
        response = llm.invoke([
            SystemMessage(content=_INTENT_SYSTEM),
            _HM(content="/no_think\n" + text[:300]),
        ])
        content = response.content or ""
        # <think>...</think> Block entfernen (Qwen3 denkt immer erst)
        import re as _re
        content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL)
        content = _re.sub(r"<think>.*", "", content, flags=_re.DOTALL)
        raw = content.strip().lower().split()[0] if content.strip() else ""
        if raw in _INTENT_CATEGORIES:
            log.debug("Intent: '%s' → %s", text[:60], raw)
            return raw
        log.warning("classify_intent_llm: unbekannte Kategorie '%s' — fallback song_default", raw)
    except Exception as exc:
        log.warning("classify_intent_llm fehlgeschlagen: %s — fallback song_default", exc)
    return "song_default"


_NOTE_INPUT_LAUNCHPAD_KW = frozenset([
    "launchpad", "selbst", "selber", "live", "einspielen", "manuell",
    "ich spiel", "ich möchte spielen", "ich mach", "von mir",
])

def classify_note_input_answer(text: str) -> str:
    """Klassifiziert die User-Antwort auf die Noten-Eingabe-Frage.

    Gibt "launchpad" zurück wenn der User selbst spielen will, sonst "agent".
    """
    lower = text.lower()
    if any(kw in lower for kw in _NOTE_INPUT_LAUNCHPAD_KW):
        return "launchpad"
    return "agent"


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
            return "done"
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
    """Gibt alle Tools zurück — kein Filtering, das Modell entscheidet."""
    user_text = _latest_user_text(all_messages)
    phase = _effective_generation_phase(all_messages, generation_phase, user_text)
    all_tools = get_tools_fn()
    log.info(
        "Router: phase=%s intent=%s -> %d Tools (alle sichtbar)",
        phase, intent or "none", len(all_tools),
    )
    return all_tools
