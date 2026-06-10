from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import AIMessage
from src.agent.router import _latest_user_text

_FX_NAMES = {
    "distortion", "amp", "compressor", "compressor+", "eq-5", "eq+",
    "reverb", "delay", "chorus", "flanger", "phaser", "limiter",
    "saturator", "transient control", "echo",
}

_CONCRETE_TASK_KEYWORDS = [
    "erstelle", "create", "mach", "baue", "bpm", "track", "riff",
    "instrument", "phase-4", "fm-4", "polysynth", "drums", "bass",
]

# Halluzinierte Tool-Namen die nie existiert haben oder entfernt wurden
_DEAD_TOOLS = frozenset([
    "setup_instrument_track", "write_notes_to_clip", "build_song",
    "bitwig_load_instrument", "bitwig_load_sample", "add_track",
    "bitwig_set_parameter", "bitwig_add_instrument_track",
    # Phase-3-entfernte Tools (LLM könnte sie noch kennen)
    "check_bitwig_connection", "get_bitwig_track_state",
    "query_bitwig_docs", "get_song_context", "get_artist_context",
    "search_artist_song", "list_known_songs",
    "suggest_notes", "arm_track", "listen_played_notes", "get_launchpad_mode",
    "set_launchpad_mode", "play_notes", "find_audio_example", "analyze_song",
    "scan_vst_plugins", "export_mlx_training_data",
])


def _extract_explicit_fx(text: str) -> list[str]:
    lower = text.lower()
    out: list[str] = []
    for fx in _FX_NAMES:
        if fx in lower and fx not in out:
            out.append(fx)
    return out


def _is_strict_fx_request(text: str) -> bool:
    lower = text.lower()
    markers = ["nur", "exakt", "genau", "fx-chain", "fx chain", "fx-kette", "kette"]
    return any(m in lower for m in markers)


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

    dead_violations = [tc["name"] for tc in calls if tc.get("name") in _DEAD_TOOLS]
    if dead_violations:
        clean_calls = [tc for tc in calls if tc.get("name") not in _DEAD_TOOLS]
        new_msg = AIMessage(content=response.content, tool_calls=clean_calls)
        return new_msg, {
            "action": "rewrite",
            "violations": dead_violations,
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
