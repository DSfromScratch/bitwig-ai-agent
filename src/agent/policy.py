from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

_NUDGE_PREFIX = "Deine Antwort war leer."

_FX_NAMES = {
    "distortion", "amp", "compressor", "compressor+", "eq-5", "eq+",
    "reverb", "delay", "chorus", "flanger", "phaser", "limiter",
    "saturator", "transient control", "echo",
}


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
    from src.agent.routing import DEFAULT_ROUTER
    return DEFAULT_ROUTER.route(user_text) == "master_graph"


def _safe_load_notes(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [n for n in raw if isinstance(n, dict)]
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [n for n in data if isinstance(n, dict)]
        except json.JSONDecodeError:
            return []
    return []


def _default_notes(length_beats: float) -> list[dict[str, float]]:
    phrase = [40, 43, 45, 47, 50, 52, 47, 50]
    out: list[dict[str, float]] = []
    step = 0.0
    while step < length_beats:
        pitch = phrase[int(step) % len(phrase)]
        out.append({"step": step, "pitch": float(pitch), "vel": 0.8, "dur": 1.0})
        step += 1.0
    return out


def _notes_length(notes: list[dict[str, Any]], default: float) -> float:
    if not notes:
        return default
    end = default
    for n in notes:
        step = _parse_float(n.get("step", 0), 0.0)
        dur = _parse_float(n.get("dur", 1), 1.0)
        end = max(end, step + max(0.25, dur))
    return round(end, 2)


def _build_song_args_from_legacy(user_text: str, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    bpm = _extract_bpm(user_text, 120.0)
    track_index = 1
    instrument = "Phase-4"
    fx: list[str] = []
    notes: list[dict[str, Any]] = []

    for tc in tool_calls:
        name = tc.get("name")
        args = tc.get("args", {})
        if not isinstance(args, dict):
            continue
        if name == "setup_instrument_track":
            track_index = int(args.get("track_index", track_index))
            candidate = str(args.get("instrument_name", "")).strip()
            if not candidate:
                continue
            if candidate.lower() in _FX_NAMES:
                if candidate not in fx:
                    fx.append(candidate)
            elif instrument == "Phase-4":
                instrument = candidate
        elif name == "bitwig_set_tempo":
            bpm = _parse_float(args.get("bpm", bpm), bpm)
        elif name == "control_bitwig":
            if str(args.get("action", "")).lower() == "tempo":
                bpm = _parse_float(args.get("value", bpm), bpm)
        elif name == "write_notes_to_clip":
            track_index = int(args.get("track_index", track_index))
            notes = _safe_load_notes(args.get("notes_json"))

    explicit_fx = _extract_explicit_fx(user_text)
    strict_fx = bool(explicit_fx) and _is_strict_fx_request(user_text)
    if strict_fx:
        fx = [f for f in fx if f.lower() in explicit_fx]

    explicit_beats = _extract_beats(user_text)
    length_guess = explicit_beats if explicit_beats is not None else _beats_from_time(bpm, user_text)
    if length_guess is None:
        length_guess = 16.0
    length_beats = _notes_length(notes, length_guess)
    if not notes:
        notes = _default_notes(length_beats)

    project = {
        "bpm": bpm,
        "tracks": [
            {
                "index": track_index,
                "instrument": instrument,
                "fx": fx,
                "clip": {
                    "slot": 0,
                    "length_beats": length_beats,
                    "notes": notes,
                },
            }
        ],
    }

    return {"project_json": json.dumps(project, ensure_ascii=False)}


def synthesize_build_song_args(user_text: str) -> dict[str, Any]:
    """Erzeugt build_song-Argumente nur aus Prompt-Heuristiken (ohne Legacy-Calls)."""
    return _build_song_args_from_legacy(user_text, [])


def enforce_policy_on_response(state: dict[str, Any], response: AIMessage) -> tuple[AIMessage, dict[str, Any]]:
    if not getattr(response, "tool_calls", None):
        return response, {"action": "none", "violations": []}

    messages = state.get("messages", [])
    user_text = _latest_user_text(messages)
    concrete = is_concrete_track_task(user_text)
    calls = list(response.tool_calls or [])

    has_build = any(tc.get("name") == "build_song" for tc in calls)
    has_legacy = any(tc.get("name") in {"setup_instrument_track", "write_notes_to_clip"} for tc in calls)
    has_wrong_song_path = any(tc.get("name") in {"create_song_from_genre", "create_song_with_sections"} for tc in calls)

    if not concrete:
        return response, {"action": "allow", "violations": []}

    if has_build and not has_legacy:
        return response, {"action": "allow", "violations": []}

    if not has_legacy and not has_wrong_song_path:
        return response, {"action": "allow", "violations": []}

    explicit_fx = _extract_explicit_fx(user_text)
    strict_fx = bool(explicit_fx) and _is_strict_fx_request(user_text)

    build_args = _build_song_args_from_legacy(user_text, calls)
    build_call = {
        "name": "build_song",
        "args": build_args,
        "id": "policy_build_song",
        "type": "tool_call",
    }

    keep: list[dict[str, Any]] = []
    for tc in calls:
        name = tc.get("name")
        if name in {"check_bitwig_connection", "verify_song"}:
            keep.append(tc)

    rewritten: list[dict[str, Any]] = []
    had_check = any(tc.get("name") == "check_bitwig_connection" for tc in keep)
    had_verify = any(tc.get("name") == "verify_song" for tc in keep)

    if had_check:
        rewritten.extend([tc for tc in keep if tc.get("name") == "check_bitwig_connection"])
    rewritten.append(build_call)
    if had_verify:
        rewritten.extend([tc for tc in keep if tc.get("name") == "verify_song"])

    new_msg = AIMessage(
        content="PolicyGuard: konkrete Track-Aufgabe erkannt; Legacy-Tool-Kette auf build_song umgeschrieben.",
        tool_calls=rewritten,
    )
    violations = ["legacy_track_chain_without_build_song"] if has_legacy else ["concrete_track_task_wrong_song_path"]

    meta = {
        "action": "rewrite",
        "violations": violations,
        "concrete_track_task": True,
        "strict_fx_request": strict_fx,
        "explicit_fx": explicit_fx,
    }
    if strict_fx:
        meta["violations"].append("strict_fx_chain_enforced")
    return new_msg, meta
