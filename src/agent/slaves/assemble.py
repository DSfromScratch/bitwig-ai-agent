"""Assemble-Node — merged Slave-Outputs zu einem build_song JSON.

Liest slave_results aus dem State (Fan-in Liste mit {type: instrument/notes/harmony}),
merged die Teile und baut den build_song JSON-String zusammen.
"""
from __future__ import annotations

import json
import logging

from src.agent.state import AgentState

log = logging.getLogger("bitwig-agent.assemble")

_MAX_SLAVE_RETRIES = 3


def _genre_role_defaults(genre: str) -> dict:
    g = (genre or "").lower()
    if "metal" in g:
        return {
            "bass": {"instrument": "Polysynth", "fx": ["Compressor", "Distortion"]},
            "chords": {"instrument": "Phase-4", "fx": ["EQ-5"]},
            "lead": {"instrument": "FM-4", "fx": ["Delay", "Distortion"]},
            "drums": {"instrument": "Drum Machine", "fx": []},
            "pad": {"instrument": "Phase-4", "fx": ["Chorus"]},
        }
    if "jazz" in g:
        return {
            "bass": {"instrument": "Organ", "fx": ["Compressor"]},
            "chords": {"instrument": "E-Piano", "fx": ["Reverb"]},
            "lead": {"instrument": "FM-4", "fx": ["Reverb"]},
            "drums": {"instrument": "Drum Machine", "fx": []},
            "pad": {"instrument": "E-Piano", "fx": ["Chorus"]},
        }
    if "edm" in g or "house" in g or "hip-hop" in g:
        return {
            "bass": {"instrument": "Phase-4", "fx": ["Compressor", "Bit-8"]},
            "chords": {"instrument": "Polysynth", "fx": ["Reverb", "Chorus"]},
            "lead": {"instrument": "FM-4", "fx": ["Delay", "Reverb"]},
            "drums": {"instrument": "Drum Machine", "fx": []},
            "pad": {"instrument": "Polysynth", "fx": ["Chorus"]},
        }
    # Default (rock/pop/blues/etc.)
    return {
        "bass": {"instrument": "Polysynth", "fx": ["Compressor"]},
        "chords": {"instrument": "Polysynth", "fx": ["Reverb", "EQ-5"]},
        "lead": {"instrument": "FM-4", "fx": ["Delay", "Reverb"]},
        "drums": {"instrument": "Drum Machine", "fx": []},
        "pad": {"instrument": "Phase-4", "fx": ["Chorus"]},
    }


def _expand_notes(notes: list[dict], target_beats: float, pattern_beats: float) -> list[dict]:
    """Wiederholt eine kurze Notensequenz bis zur Ziel-Länge.

    z.B. 8 Noten über 8 Beats → 4x wiederholen für 40-Beat-Clip.
    """
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


def _clamp_register(notes: list[dict], low: int, high: int) -> list[dict]:
    out: list[dict] = []
    for n in notes:
        p = int(n["pitch"])
        out.append({**n, "pitch": max(low, min(high, p))})
    return out


def _transpose(notes: list[dict], semitones: int) -> list[dict]:
    out: list[dict] = []
    for n in notes:
        out.append({**n, "pitch": int(n["pitch"]) + semitones})
    return out


def _build_chord_track_notes(target_beats: float, harmony_result: dict) -> list[dict]:
    preferred = [int(p) for p in (harmony_result.get("preferred_pitches") or [])]
    if len(preferred) < 3:
        preferred = [48, 52, 55]

    notes: list[dict] = []
    step = 0.0
    while step < target_beats:
        for p in preferred[:3]:
            notes.append({"step": round(step, 4), "pitch": int(p), "vel": 0.62, "dur": 1.75})
        step += 2.0
    return notes


def _build_drum_notes(target_beats: float) -> list[dict]:
    notes: list[dict] = []
    beat = 0.0
    while beat < target_beats:
        # Kick on 1 and 3
        if int(beat) % 4 in (0, 2):
            notes.append({"step": round(beat, 4), "pitch": 36, "vel": 0.9, "dur": 0.25})
        # Snare on 2 and 4
        if int(beat) % 4 in (1, 3):
            notes.append({"step": round(beat, 4), "pitch": 38, "vel": 0.82, "dur": 0.25})
        # Hi-hat every 1/2 beat
        notes.append({"step": round(beat, 4), "pitch": 42, "vel": 0.55, "dur": 0.1})
        notes.append({"step": round(beat + 0.5, 4), "pitch": 42, "vel": 0.48, "dur": 0.1})
        beat += 1.0
    return [n for n in notes if n["step"] < target_beats]


def assemble_node(state: AgentState) -> dict:
    """Node-Funktion für den Master-Graph.

    Gibt assembled_json zurück wenn beide Slaves erfolgreich waren,
    oder slave_results mit retry-Einträgen wenn nicht.
    """
    results = state.get("slave_results") or []
    plan = state.get("slave_plan") or {}

    instrument_result = next((r for r in results if r.get("type") == "instrument" and "error" not in r), None)
    harmony_result = next((r for r in results if r.get("type") == "harmony" and "error" not in r), None)
    notes_result = next((r for r in results if r.get("type") == "notes" and "error" not in r), None)

    errors = [r for r in results if "error" in r]
    retry_counts = state.get("slave_retry_counts") or {}

    # Prüfe ob Slaves wiederholt scheitern
    for err in errors:
        slave_type = err.get("type", "unknown")
        retries = retry_counts.get(slave_type, 0)
        if retries >= _MAX_SLAVE_RETRIES:
            log.error("Assemble: %s-Slave nach %d Versuchen gescheitert", slave_type, retries)
            return {
                "assembled_json": None,
                "generation_phase": "error",
            }

    if not instrument_result or not notes_result or not harmony_result:
        missing = []
        if not instrument_result:
            missing.append("instrument")
        if not harmony_result:
            missing.append("harmony")
        if not notes_result:
            missing.append("notes")
        log.warning("Assemble: warte auf Slaves %s", missing)
        # Signalisiert dem Graph, dass fehlende Slaves nochmal laufen sollen
        return {"assembled_json": None}

    # Noten expandieren bis zur Ziel-Länge aus slave_plan
    target_beats = float(plan.get("beat_count", notes_result["length_beats"]))
    pattern_beats = float(notes_result["length_beats"])
    notes = _expand_notes(notes_result["notes"], target_beats, pattern_beats)

    track_count = int(plan.get("track_count", 1) or 1)
    role_defaults = _genre_role_defaults(str(plan.get("genre", "")))

    tracks: list[dict] = []
    tracks.append({
        "index": 1,
        "instrument": instrument_result["instrument"],
        "preset": instrument_result.get("preset", "") or "",
        "fx_preset": instrument_result.get("fx_preset", "") or "",
        "fx": instrument_result.get("fx", []),
        "clip": {
            "slot": 0,
            "length_beats": target_beats,
            "notes": notes,
        },
    })

    if track_count >= 2:
        bass_notes = _clamp_register(_transpose(notes, -12), 36, 52)
        tracks.append({
            "index": 2,
            "instrument": role_defaults["bass"]["instrument"],
            "preset": "",
            "fx_preset": "",
            "fx": role_defaults["bass"]["fx"],
            "clip": {
                "slot": 0,
                "length_beats": target_beats,
                "notes": bass_notes,
            },
        })

    if track_count >= 3:
        tracks.append({
            "index": 3,
            "instrument": role_defaults["chords"]["instrument"],
            "preset": "",
            "fx_preset": "",
            "fx": role_defaults["chords"]["fx"],
            "clip": {
                "slot": 0,
                "length_beats": target_beats,
                "notes": _build_chord_track_notes(target_beats, harmony_result),
            },
        })

    if track_count >= 4:
        lead_notes = _clamp_register(_transpose(notes[::2] if len(notes) > 4 else notes, 12), 55, 76)
        tracks.append({
            "index": 4,
            "instrument": role_defaults["lead"]["instrument"],
            "preset": "",
            "fx_preset": "",
            "fx": role_defaults["lead"]["fx"],
            "clip": {
                "slot": 0,
                "length_beats": target_beats,
                "notes": lead_notes,
            },
        })

    if track_count >= 5:
        tracks.append({
            "index": 5,
            "instrument": role_defaults["drums"]["instrument"],
            "preset": "",
            "fx_preset": "",
            "fx": role_defaults["drums"]["fx"],
            "clip": {
                "slot": 0,
                "length_beats": target_beats,
                "notes": _build_drum_notes(target_beats),
            },
        })

    if track_count >= 6:
        pad_notes = []
        pad_pref = [int(p) for p in (harmony_result.get("preferred_pitches") or [48, 52, 55])]
        for i in range(0, int(target_beats), 4):
            for p in pad_pref[:3]:
                pad_notes.append({"step": float(i), "pitch": p, "vel": 0.45, "dur": 3.5})
        tracks.append({
            "index": 6,
            "instrument": role_defaults["pad"]["instrument"],
            "preset": "",
            "fx_preset": "",
            "fx": role_defaults["pad"]["fx"],
            "clip": {
                "slot": 0,
                "length_beats": target_beats,
                "notes": pad_notes,
            },
        })

    project = {
        "bpm": notes_result["bpm"],
        "tracks": tracks,
    }

    assembled = json.dumps(project, ensure_ascii=False)
    log.info(
        "Assemble: %d Track(s), main=%s, %d Noten (%.0f Beats) → build_song JSON (%d Bytes)",
        len(tracks),
        instrument_result["instrument"],
        len(notes),
        target_beats,
        len(assembled),
    )
    return {"assembled_json": assembled, "generation_phase": "generating"}
