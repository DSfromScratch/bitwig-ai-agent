"""Assemble-Node — merged Slave-Outputs zu einem build_song JSON."""
from __future__ import annotations

import json
import logging

from src.agent.state import AgentState

log = logging.getLogger("bitwig-agent.assemble")

_MAX_SLAVE_RETRIES = 3


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

    target_beats  = float(plan.get("beat_count", notes_result["length_beats"]))
    pattern_beats = float(notes_result["length_beats"])
    notes_by_role: dict[str, list] = notes_result.get("roles", {})

    _DRUM_ROLES = {"kick", "snare", "hihat", "clap", "tom", "openhat", "crash"}

    drum_defs    = [td for td in tracks_manifest if td["role"] in _DRUM_ROLES]
    melodic_defs = [td for td in tracks_manifest if td["role"] not in _DRUM_ROLES]

    tracks: list[dict] = []
    track_idx = 1

    # Jede Drum-Rolle → eigener Instrument-Track (vermeidet Drum-Machine-Pad-Navigation via OSC)
    for td in drum_defs:
        role = td["role"]
        role_notes = notes_by_role.get(role, [])
        expanded = _expand_notes(role_notes, target_beats, pattern_beats)
        tracks.append({
            "index": track_idx,
            "instrument": td["instrument"],
            "preset": td.get("preset", "") or "",
            "fx_preset": td.get("fx_preset", "") or "",
            "fx": td.get("fx", []),
            "clip": {
                "slot": 0,
                "length_beats": target_beats,
                "notes": expanded,
            },
        })
        track_idx += 1

    # Melodische Tracks
    for track_def in melodic_defs:
        role  = track_def["role"]
        notes = _expand_notes(notes_by_role.get(role, []), target_beats, pattern_beats)
        tracks.append({
            "index": track_idx,
            "instrument": track_def["instrument"],
            "preset":    track_def.get("preset", "") or "",
            "fx_preset": track_def.get("fx_preset", "") or "",
            "fx":        track_def.get("fx", []),
            "clip": {
                "slot": 0,
                "length_beats": target_beats,
                "notes": notes,
            },
        })
        track_idx += 1

    # ── Return-Tracks aus fx_hint ableiten ───────────────────────────────────
    fx_hint   = (plan.get("fx_hint") or "").lower()
    user_text = (plan.get("user_text") or "").lower()
    return_tracks: list[dict] = []
    if any(kw in fx_hint or kw in user_text for kw in ("reverb", "hall", "room", "plate", "return", "send")):
        return_tracks.append({"name": "Reverb Send", "device": "Reverb"})
    if any(kw in fx_hint or kw in user_text for kw in ("delay", "echo")):
        return_tracks.append({"name": "Delay Send", "device": "Delay+"})

    # Sends: nur melodische Rollen bekommen Reverb/Delay
    _WET_ROLES = {"bass", "pad", "chords", "lead", "melody", "keys", "synth"}
    if return_tracks:
        for t in tracks:
            role = next(
                (td["role"] for td in tracks_manifest if td["instrument"] == t["instrument"]),
                "",
            )
            sends = []
            for rt in return_tracks:
                if role in _WET_ROLES:
                    sends.append(0.55 if "reverb" in rt["name"].lower() else 0.35)
                else:
                    sends.append(0.0)
            if any(s > 0 for s in sends):
                t["sends"] = sends

    project: dict = {"bpm": notes_result["bpm"], "tracks": tracks}
    if return_tracks:
        project["return_tracks"] = return_tracks

    assembled = json.dumps(project, ensure_ascii=False)

    roles = [t["role"] for t in tracks_manifest]
    rt_info = f", {len(return_tracks)} Return-Track(s)" if return_tracks else ""
    log.info(
        "Assemble: %d Track(s) %s%s, %.0f Beats → %d Bytes",
        len(tracks), roles, rt_info, target_beats, len(assembled),
    )
    return {"assembled_json": assembled, "generation_phase": "generating"}
