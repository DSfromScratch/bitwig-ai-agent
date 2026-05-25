"""Assemble-Node — merged Slave-Outputs zu einem build_song JSON.

InstrumentSlave liefert jetzt eine vollständige Track-Manifest-Liste.
Für jede Rolle werden Noten programmatisch generiert (Drums) oder
aus dem NoteSlave-Output abgeleitet (Bass, Chords, Lead, Pad, Melody).
"""
from __future__ import annotations

import json
import logging

from src.agent.state import AgentState

log = logging.getLogger("bitwig-agent.assemble")

_MAX_SLAVE_RETRIES = 3


# ── Programmatische Noten-Generatoren pro Rolle ───────────────────────────────

def _build_kick_notes(target_beats: float) -> list[dict]:
    notes = []
    beat = 0.0
    while beat < target_beats:
        if int(beat) % 4 in (0, 2):
            notes.append({"step": round(beat, 4), "pitch": 36, "vel": 0.90, "dur": 0.25})
        beat += 1.0
    return notes


def _build_snare_notes(target_beats: float) -> list[dict]:
    notes = []
    beat = 0.0
    while beat < target_beats:
        if int(beat) % 4 in (1, 3):
            notes.append({"step": round(beat, 4), "pitch": 38, "vel": 0.82, "dur": 0.25})
        beat += 1.0
    return notes


def _build_hihat_notes(target_beats: float) -> list[dict]:
    notes = []
    step = 0.0
    while step < target_beats:
        vel = 0.55 if round(step % 1.0, 4) == 0.0 else 0.42
        notes.append({"step": round(step, 4), "pitch": 42, "vel": vel, "dur": 0.1})
        step = round(step + 0.5, 4)
    return notes


def _build_bass_notes(target_beats: float, harmony_result: dict) -> list[dict]:
    preferred = [int(p) for p in (harmony_result.get("preferred_pitches") or [])]
    root = preferred[0] if preferred else 40
    # Root eine Oktave tiefer, auf dem Downbeat
    root_low = max(28, root - 12)
    notes = []
    beat = 0.0
    while beat < target_beats:
        notes.append({"step": round(beat, 4), "pitch": root_low, "vel": 0.82, "dur": 0.75})
        beat += 2.0
    return notes


def _build_chord_notes(target_beats: float, harmony_result: dict) -> list[dict]:
    preferred = [int(p) for p in (harmony_result.get("preferred_pitches") or [])]
    if len(preferred) < 3:
        preferred = [48, 52, 55]
    notes = []
    step = 0.0
    while step < target_beats:
        for p in preferred[:3]:
            notes.append({"step": round(step, 4), "pitch": int(p), "vel": 0.62, "dur": 1.75})
        step += 2.0
    return notes


def _build_pad_notes(target_beats: float, harmony_result: dict) -> list[dict]:
    preferred = [int(p) for p in (harmony_result.get("preferred_pitches") or [48, 52, 55])]
    notes = []
    for i in range(0, int(target_beats), 4):
        for p in preferred[:3]:
            notes.append({"step": float(i), "pitch": int(p), "vel": 0.42, "dur": 3.5})
    return notes


def _expand_notes(notes: list[dict], target_beats: float, pattern_beats: float) -> list[dict]:
    if not notes or pattern_beats <= 0 or target_beats <= pattern_beats:
        return notes
    expanded = []
    offset = 0.0
    while offset < target_beats:
        for n in notes:
            new_step = round(n["step"] + offset, 4)
            if new_step >= target_beats:
                break
            expanded.append({**n, "step": new_step})
        offset += pattern_beats
    return expanded


def _clamp(notes: list[dict], low: int, high: int) -> list[dict]:
    return [{**n, "pitch": max(low, min(high, int(n["pitch"])))} for n in notes]


def _transpose(notes: list[dict], semitones: int) -> list[dict]:
    return [{**n, "pitch": int(n["pitch"]) + semitones} for n in notes]


# ── MIDI-Bereiche je Rolle (aus instrument_registry) ─────────────────────────

def _midi_range(role: str) -> tuple[int, int]:
    try:
        from src.audio.instrument_registry import get_instrument
        tmpl = get_instrument(role)
        return tmpl["midi_low"], tmpl["midi_high"]
    except Exception:
        pass
    defaults = {
        "kick": (36, 36), "snare": (38, 38), "hihat": (42, 42),
        "bass": (28, 52), "chords": (48, 72), "lead": (55, 84),
        "pad": (48, 72), "melody": (55, 84),
    }
    return defaults.get(role, (36, 84))


# ── Noten für eine Rolle ──────────────────────────────────────────────────────

def _notes_for_role(
    role: str,
    notes_result: dict,
    harmony_result: dict,
    target_beats: float,
) -> list[dict]:
    pattern_beats = float(notes_result["length_beats"])
    raw_notes = notes_result["notes"]

    if role == "kick":
        return _build_kick_notes(target_beats)
    if role == "snare":
        return _build_snare_notes(target_beats)
    if role == "hihat":
        return _build_hihat_notes(target_beats)
    if role == "bass":
        notes = _build_bass_notes(target_beats, harmony_result)
        low, high = _midi_range("bass")
        return _clamp(notes, low, high)
    if role == "chords":
        return _build_chord_notes(target_beats, harmony_result)
    if role == "pad":
        return _build_pad_notes(target_beats, harmony_result)
    if role in ("lead", "melody"):
        low, high = _midi_range(role)
        notes = _expand_notes(raw_notes, target_beats, pattern_beats)
        return _clamp(notes, low, high)
    # Unbekannte Rolle → expandierte LLM-Noten
    return _expand_notes(raw_notes, target_beats, pattern_beats)


# ── Assemble-Node ─────────────────────────────────────────────────────────────

def assemble_node(state: AgentState) -> dict:
    results = state.get("slave_results") or []
    plan = state.get("slave_plan") or {}

    instrument_result = next(
        (r for r in results if r.get("type") == "instrument" and "error" not in r), None
    )
    harmony_result = next(
        (r for r in results if r.get("type") == "harmony" and "error" not in r), None
    )
    notes_result = next(
        (r for r in results if r.get("type") == "notes" and "error" not in r), None
    )

    errors = [r for r in results if "error" in r]
    retry_counts = state.get("slave_retry_counts") or {}

    for err in errors:
        slave_type = err.get("type", "unknown")
        if retry_counts.get(slave_type, 0) >= _MAX_SLAVE_RETRIES:
            log.error("Assemble: %s-Slave nach %d Versuchen gescheitert", slave_type, _MAX_SLAVE_RETRIES)
            return {"assembled_json": None, "generation_phase": "error"}

    if not instrument_result or not notes_result or not harmony_result:
        missing = [n for n, r in [("instrument", instrument_result),
                                   ("harmony", harmony_result),
                                   ("notes", notes_result)] if not r]
        log.warning("Assemble: warte auf Slaves %s", missing)
        return {"assembled_json": None}

    tracks_manifest: list[dict] = instrument_result.get("tracks", [])
    if not tracks_manifest:
        log.error("Assemble: InstrumentSlave lieferte leere Track-Liste")
        return {"assembled_json": None, "generation_phase": "error"}

    target_beats = float(plan.get("beat_count", notes_result["length_beats"]))

    tracks: list[dict] = []
    for i, track_def in enumerate(tracks_manifest, start=1):
        role = track_def["role"]
        notes = _notes_for_role(role, notes_result, harmony_result, target_beats)
        tracks.append({
            "index": i,
            "instrument": track_def["instrument"],
            "preset": track_def.get("preset", "") or "",
            "fx_preset": track_def.get("fx_preset", "") or "",
            "fx": track_def.get("fx", []),
            "clip": {
                "slot": 0,
                "length_beats": target_beats,
                "notes": notes,
            },
        })

    project = {"bpm": notes_result["bpm"], "tracks": tracks}
    assembled = json.dumps(project, ensure_ascii=False)

    roles = [t["role"] for t in tracks_manifest]
    log.info(
        "Assemble: %d Track(s) %s, %.0f Beats → %d Bytes",
        len(tracks), roles, target_beats, len(assembled),
    )
    return {"assembled_json": assembled, "generation_phase": "generating"}
