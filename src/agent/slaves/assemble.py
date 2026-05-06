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

    project = {
        "bpm": notes_result["bpm"],
        "tracks": [
            {
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
            }
        ],
    }

    assembled = json.dumps(project, ensure_ascii=False)
    log.info(
        "Assemble: %s + %d Noten (%.0f Beats) → build_song JSON (%d Bytes)",
        instrument_result["instrument"],
        len(notes),
        target_beats,
        len(assembled),
    )
    return {"assembled_json": assembled, "generation_phase": "generating"}
