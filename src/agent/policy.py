from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

_NUDGE_PREFIX = "Deine Antwort war leer."

_FX_NAMES = {
    "distortion", "amp", "compressor", "compressor+", "eq-5", "eq+",
    "reverb", "delay", "chorus", "flanger", "phaser", "limiter",
    "saturator", "transient control", "echo",
}

# Keywords die auf eine konkrete Track-Aufgabe hindeuten
_CONCRETE_TASK_KEYWORDS = [
    "erstelle", "create", "mach", "baue", "bpm", "track", "riff",
    "instrument", "phase-4", "fm-4", "polysynth", "drums", "bass",
]


def _extract_explicit_fx(text: str) -> list[str]:
    """Extrahiert explizit genannte FX in stabiler Reihenfolge."""
    lower = text.lower()
    out: list[str] = []
    for fx in _FX_NAMES:
        if fx in lower and fx not in out:
            out.append(fx)
    return out


def _is_strict_fx_request(text: str) -> bool:
    """Erkennt enge Vorgaben wie 'nur', 'exakt' oder 'FX-Chain'."""
    lower = text.lower()
    markers = ["nur", "exakt", "genau", "fx-chain", "fx chain", "fx-kette", "kette"]
    return any(m in lower for m in markers)


def _latest_user_text(messages: list[Any]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            text = (m.content or "").strip()
            if text and not text.startswith(_NUDGE_PREFIX):
                return text
    return ""


def _parse_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_bpm(text: str, default: float = 120.0) -> float:
    m = re.search(r"(\d{2,3})\s*bpm", text.lower())
    if m:
        return _parse_float(m.group(1), default)
    return default


def _extract_seconds(text: str) -> float | None:
    lower = text.lower()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(sekunden|sek|seconds|second)", lower)
    if not m:
        return None
    raw = m.group(1).replace(",", ".")
    return _parse_float(raw, 0.0)


def _extract_beats(text: str) -> float | None:
    lower = text.lower()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(beats|beat)\b", lower)
    if not m:
        return None
    raw = m.group(1).replace(",", ".")
    val = _parse_float(raw, 0.0)
    return val if val > 0 else None


def _beats_from_time(bpm: float, text: str) -> float | None:
    sec = _extract_seconds(text)
    if sec is None or sec <= 0:
        return None
    return max(1.0, round(sec * bpm / 60.0, 2))


def is_concrete_track_task(user_text: str) -> bool:
    """Erkennt ob der User eine konkrete Track-/Song-Aufgabe stellt."""
    lower = user_text.lower()
    matches = sum(1 for kw in _CONCRETE_TASK_KEYWORDS if kw in lower)
    return matches >= 2


def enforce_policy_on_response(state: dict[str, Any], response: AIMessage) -> tuple[AIMessage, dict[str, Any]]:
    if not getattr(response, "tool_calls", None):
        return response, {"action": "none", "violations": []}

    messages = state.get("messages", [])
    user_text = _latest_user_text(messages)
    concrete = is_concrete_track_task(user_text)
    calls = list(response.tool_calls or [])

    # Halluzinierte Legacy-Tools die nie existiert haben
    _DEAD_TOOLS = {"setup_instrument_track", "write_notes_to_clip", "build_song",
                   "bitwig_load_instrument", "bitwig_load_sample", "add_track",
                   "bitwig_set_parameter", "bitwig_add_instrument_track"}
    violations = [tc["name"] for tc in calls if tc.get("name") in _DEAD_TOOLS]

    if violations:
        # Tote Tool-Calls herausfiltern — Agent soll ohne sie weitermachen
        clean_calls = [tc for tc in calls if tc.get("name") not in _DEAD_TOOLS]
        if not clean_calls:
            return response, {"action": "none", "violations": violations}
        new_msg = AIMessage(content=response.content, tool_calls=clean_calls)
        return new_msg, {
            "action": "rewrite",
            "violations": violations,
            "concrete_track_task": concrete,
            "strict_fx_request": False,
            "explicit_fx": [],
        }

    explicit_fx = _extract_explicit_fx(user_text)
    strict_fx = bool(explicit_fx) and _is_strict_fx_request(user_text)
    return response, {
        "action": "allow",
        "violations": [],
        "concrete_track_task": concrete,
        "strict_fx_request": strict_fx,
        "explicit_fx": explicit_fx,
    }
